#!/bin/bash
# Pushes to Uptime Kuma's push monitors every 5 minutes via wan-check.timer.
#
# Covers the five things nothing else can see:
#   1. each ISP line, end to end and independently
#   2. Pi-hole actually blocking, not merely resolving
#   3. the blocklist still being fresh
#   4. rejected SSH attempts, which on this LAN can't be you
#   5. whether a human needs to do something
set -u

# Default empty so an .env written before this check existed simply disables the
# SSH monitor, rather than tripping `set -u` and killing the script - which would
# take all eleven other monitors down with it, silently, at the next timer tick.
KUMA_PUSH_SSH=""

# .env is data, not shell. Sourcing it would EXECUTE anything after a ";" and
# PIHOLE_UPSTREAMS / PIHOLE_HOSTS legitimately contain semicolons and spaces,
# because that's the format Pi-hole and docker compose want. Read only the keys
# this script needs, matched against a whitelist, with no evaluation.
while IFS='=' read -r k v; do
    case "$k" in
        WAN1_SRC|WAN1_EXPECT|WAN2_SRC|WAN2_EXPECT|KUMA_PUSH_*)
            printf -v "$k" '%s' "$v" ;;
    esac
done < /srv/navi/.env

KUMA="http://localhost:3001/api/push"

# -G --data-urlencode does real URL encoding. A hand-rolled "spaces to %20"
# breaks on any message containing % or &, e.g. "disk 87% full".
push() { curl -s -m 10 -o /dev/null -G --data-urlencode "msg=$3" "$KUMA/$1?status=$2&ping=$4"; }

# --- per-WAN, end to end -----------------------------------------------------
#
# HTTP, not ping, and this is not a style choice. The ER605 applies policy
# routing only to tracked TCP sessions; UDP and ICMP ignore it and fall back to
# load balancing even with Service Type set to ALL. Verified 2026-09-03: dig -b
# and traceroute -I from both source IPs went out Megacable, while HTTPS from
# .61 went out Telmex 6 times out of 6.
#
# So a `ping -I <source>` monitor would sit green while measuring whichever line
# the load balancer felt like. Green, meaningless, indistinguishable from
# working.
#
# Each run also reports the egress IP, which makes the check prove its own path.
# If the policy route breaks, this says so instead of quietly testing the
# surviving line.
check_wan() {
    local src="$1" expect="$2" token="$3" label="$4"
    local ip="" t0 t1 ms
    t0=$(date +%s%N)
    for url in https://api.ipify.org https://icanhazip.com; do
        ip=$(curl -s -m 10 --interface "$src" "$url" 2>/dev/null | tr -d '[:space:]')
        [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
        ip=""
    done
    t1=$(date +%s%N); ms=$(( (t1 - t0) / 1000000 ))

    if [ -z "$ip" ]; then
        push "$token" down "$label DOWN - no route to internet via $src" "$ms"
    elif [ "$ip" != "$expect" ]; then
        push "$token" down "ROUTE BROKEN - egress $ip expected $expect" "$ms"
    else
        push "$token" up "$ip" "$ms"
    fi
}
check_wan "$WAN1_SRC" "$WAN1_EXPECT" "$KUMA_PUSH_WAN1" "Telmex"
check_wan "$WAN2_SRC" "$WAN2_EXPECT" "$KUMA_PUSH_WAN2" "Megacable"

# --- Pi-hole is blocking, not just resolving ---------------------------------
#
# A wiped gravity list looks identical to a healthy resolver from every other
# angle: DNS works, uptime is fine, nothing goes red, ads just come back.
#
# Two canaries, alarming only if both resolve. One canary is fragile because
# lists legitimately drop individual domains. That happened on 2026-09-03: the
# canary was doubleclick.net, and HaGeZi deliberately does not block that apex,
# only its ad-serving subdomains, so a healthy Pi-hole reported NOT BLOCKING.
c1=$(dig +short +time=3 +tries=1 @127.0.0.1 pagead2.googlesyndication.com 2>/dev/null | head -1)
c2=$(dig +short +time=3 +tries=1 @127.0.0.1 securepubads.g.doubleclick.net 2>/dev/null | head -1)
resolved=$(dig +short +time=3 +tries=1 @127.0.0.1 github.com 2>/dev/null | head -1)
if [ -z "$resolved" ]; then
    push "$KUMA_PUSH_BLOCKING" down "resolver not answering" 0
elif [ "$c1" != "0.0.0.0" ] && [ "$c2" != "0.0.0.0" ]; then
    push "$KUMA_PUSH_BLOCKING" down "NOT BLOCKING - both canaries resolved" 0
else
    push "$KUMA_PUSH_BLOCKING" up "blocking ok" 0
fi

# --- blocklist freshness -----------------------------------------------------
#
# Gravity updates weekly from cron inside the container (45 3 * * 0). If that
# fails, Pi-hole serves the stale list and reports nothing. 10 days is the
# weekly schedule plus 3 days grace, so one missed run is tolerated and two are
# not. The domain-count floor catches an "update" that fetched an error page.
GDB=/srv/data/pihole/etc-pihole/gravity.db
gts=$(sqlite3 "$GDB" "select value from info where property='updated'" 2>/dev/null)
gct=$(sqlite3 "$GDB" "select value from info where property='gravity_count'" 2>/dev/null)
if [ -z "$gts" ] || [ -z "$gct" ]; then
    push "$KUMA_PUSH_GRAVITY" down "cannot read gravity.db" 0
else
    age_d=$(( ( $(date +%s) - gts ) / 86400 ))
    if [ "$gct" -lt 1000 ]; then
        push "$KUMA_PUSH_GRAVITY" down "blocklist collapsed - only $gct domains" 0
    elif [ "$age_d" -gt 10 ]; then
        push "$KUMA_PUSH_GRAVITY" down "STALE - last updated $age_d days ago ($gct domains)" 0
    else
        push "$KUMA_PUSH_GRAVITY" up "$gct domains, updated ${age_d}d ago" "$age_d"
    fi
fi

# --- is anything trying to get in over SSH? ----------------------------------
#
# SSH is key-only and never port-forwarded, so the only clients that can reach
# port 22 are already inside the flat. That makes a rejected attempt a statement
# about the LAN rather than about the internet: a compromised IoT device, a
# guest's laptop, something scanning. Rare enough to be worth an alarm.
#
# The pattern is deliberately narrow, and "Failed publickey" is deliberately NOT
# in it. ssh clients offer every key they hold and each rejected offer logs that
# line, so one perfectly normal login by you can produce two or three. Counting
# them would fire this monitor every time you did maintenance, and an alarm that
# cries wolf during routine work becomes wallpaper. What's counted is what can't
# be you: usernames that don't exist, password auth that isn't even enabled, and
# clients that burned through every attempt.
#
# Matched by syslog identifier, not by unit. Trixie socket-activates ssh into
# per-connection units, and OpenSSH 9.8+ moved authentication into a separate
# `sshd-session` binary, so `-u ssh` misses exactly the lines that matter.
SSH_ALARM=5   # also in www/index.html, where the tile turns red on the same number
SSH_STATE=/srv/data/ssh-fail
ssh_re="Invalid user|Failed password|maximum authentication attempts exceeded"

# Tell "nothing failed" apart from "we are reading the wrong place". If sshd has
# never logged a line under either identifier then the query is wrong, and a
# count of zero is a lie of exactly the shape this box was bought to catch.
if journalctl -t sshd -t sshd-session -n 1 --no-pager 2>/dev/null | grep -q .; then
    nfail=$(journalctl -t sshd -t sshd-session --since "24 hours ago" --no-pager 2>/dev/null | grep -c -E "$ssh_re")
    nfail=${nfail:-0}
    printf '%s\n' "$nfail" > "$SSH_STATE"
    if [ -n "$KUMA_PUSH_SSH" ]; then
        if [ "$nfail" -ge "$SSH_ALARM" ]; then
            push "$KUMA_PUSH_SSH" down "$nfail rejected SSH attempts in 24h - something on the LAN is trying" "$nfail"
        else
            push "$KUMA_PUSH_SSH" up "$nfail rejected in 24h" "$nfail"
        fi
    fi
else
    printf 'unknown\n' > "$SSH_STATE"
    [ -n "$KUMA_PUSH_SSH" ] && push "$KUMA_PUSH_SSH" down "cannot read the sshd journal - check the identifier" 0
fi

# --- does a human need to do something? --------------------------------------
#
# Security patches install themselves. Reboots do not, because this box is the
# flat's DNS and does not get to pick when it vanishes. So something has to ask.
issues=""
[ -f /var/run/reboot-required ] && issues="reboot required for: $(tr '\n' ' ' < /var/run/reboot-required.pkgs 2>/dev/null | cut -c1-80)"
disk=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "${disk:-0}" -gt 85 ] && issues="$issues | disk ${disk}% full"
uulog=/var/log/unattended-upgrades/unattended-upgrades.log
if [ -f "$uulog" ]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$uulog") ) / 86400 ))
    [ "$age" -gt 3 ] && issues="$issues | unattended-upgrades silent for ${age}d"
fi
if [ -n "$issues" ]; then
    push "$KUMA_PUSH_ATTENTION" down "$issues" 0
else
    push "$KUMA_PUSH_ATTENTION" up "nothing needed (disk ${disk}%)" 0
fi
