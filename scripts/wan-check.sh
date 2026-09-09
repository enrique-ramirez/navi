#!/bin/bash
# Pushes to Uptime Kuma's push monitors every 5 minutes via wan-check.timer.
#
# Covers the six things nothing else can see:
#   1. each ISP line, end to end and independently
#   2. Pi-hole actually blocking, not merely resolving
#   3. the blocklist still being fresh
#   4. rejected SSH attempts, which on this LAN can't be you
#   5. whether a human needs to do something
#   6. the box cooking itself, which the panel shows and cannot shout about
set -u

# Default empty so an .env written before either of these checks existed simply
# disables that monitor, rather than tripping `set -u` and killing the script -
# which would take every other monitor down with it, silently, at the next timer
# tick. Deploying the script and filling in .env are two separate steps, and
# between them is exactly when this matters.
KUMA_PUSH_SSH=""
KUMA_PUSH_TEMP=""

# Same reasoning, and here it is load-bearing in a different way: these keys
# replaced WAN1_EXPECT / WAN2_EXPECT, so the .env sitting on navi will not have
# them until someone edits it. Unset under `set -u` would kill the script on the
# first tick after a deploy and take all thirteen monitors down at once. Empty
# instead means the two WAN checks fall back to the weaker same-address test and
# say in their message that the ISP is unverified.
WAN1_ISP=""
WAN2_ISP=""

# .env is data, not shell. Sourcing it would EXECUTE anything after a ";" and
# PIHOLE_UPSTREAMS / PIHOLE_HOSTS legitimately contain semicolons and spaces,
# because that's the format Pi-hole and docker compose want. Read only the keys
# this script needs, matched against a whitelist, with no evaluation.
while IFS='=' read -r k v; do
    case "$k" in
        WAN1_SRC|WAN1_ISP|WAN2_SRC|WAN2_ISP|KUMA_PUSH_*)
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
# Each run also has to prove its own path, or a broken policy route would just
# re-test the surviving line and stay green. That identity check used to be a
# literal public IP per WAN, and it was wrong: neither ISP gives us a static
# address. Both lines came back on new ones after the cables were unplugged on
# 2026-09-04, and both monitors went red over a working network.
#
# The identity is the ISP, not the address. Both ISPs put their own domain in
# the PTR and keep it across a lease change, verified across both the old and
# new addresses on both lines:
#
#   187.211.43.253   dsl-...-dynamic.prod-infinitum.com.mx   Telmex, before
#   187.213.253.225  dsl-...-dynamic.prod-infinitum.com.mx   Telmex, after
#   189.196.218.19   customer-GDL-CGN-...megared.net.mx      Megacable, before
#   189.196.217.197  customer-GDL-CGN-...megared.net.mx      Megacable, after
#
# This is strictly more informative than the old check, not just more durable.
# "Egress X, expected Y" could not tell a renewed lease from a dead line, and
# said the same thing in both cases. A PTR belonging to the *other* ISP means
# traffic pinned to this line is leaving by the other one, which is the router
# having failed over, which is the silent-ISP-death this box was built for.
probe() {   # -> PROBE_IP (empty if the line is dead), PROBE_MS
    local src="$1" t0 t1
    PROBE_IP=""
    t0=$(date +%s%N)
    for url in https://api.ipify.org https://icanhazip.com; do
        PROBE_IP=$(curl -s -m 10 --interface "$src" "$url" 2>/dev/null | tr -d '[:space:]')
        [[ "$PROBE_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
        PROBE_IP=""
    done
    t1=$(date +%s%N); PROBE_MS=$(( (t1 - t0) / 1000000 ))
}

probe "$WAN1_SRC"; ip1="$PROBE_IP"; ms1="$PROBE_MS"
probe "$WAN2_SRC"; ip2="$PROBE_IP"; ms2="$PROBE_MS"

check_wan() {
    local label="$1" src="$2" token="$3" ip="$4" ms="$5" want="$6" other="$7"
    local ptr=""

    if [ -z "$ip" ]; then
        push "$token" down "$label DOWN - no route to internet via $src" "$ms"
        return
    fi

    [ -n "$want" ] && ptr=$(dig +short +time=3 +tries=1 -x "$ip" @127.0.0.1 2>/dev/null | head -1)

    if [ -n "$want" ] && [ -n "$ptr" ]; then
        case "$ptr" in
            *"$want"*) push "$token" up "$ip ($want)" "$ms" ;;
            *) push "$token" down "WRONG LINE - $src egresses $ip ($ptr), not $want" "$ms" ;;
        esac
        return
    fi

    # No PTR to check against, either because the lookup failed or because no
    # domain is configured. Fall back to the weaker invariant rather than going
    # red on a working line: two different ISPs cannot hand out the same public
    # address, so if both source IPs egress the same one, policy routing has
    # stopped separating them. That catches a collapsed route without needing
    # to know whose address it is. It cannot catch a swap, so it says so.
    local why="no PTR"
    [ -z "$want" ] && why="no ISP domain set in .env"
    if [ -n "$other" ] && [ "$ip" = "$other" ]; then
        push "$token" down "ROUTE BROKEN - both lines egress $ip" "$ms"
    else
        push "$token" up "$ip - ISP unverified, $why" "$ms"
    fi
}
check_wan "Telmex"    "$WAN1_SRC" "$KUMA_PUSH_WAN1" "$ip1" "$ms1" "$WAN1_ISP" "$ip2"
check_wan "Megacable" "$WAN2_SRC" "$KUMA_PUSH_WAN2" "$ip2" "$ms2" "$WAN2_ISP" "$ip1"

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

# --- is navi running hot? ----------------------------------------------------
#
# The landing page has shown this number since day one and cannot shout about
# it. Nothing else in the flat would notice the copper block working loose, or
# a summer afternoon in a kitchen, until the box started throttling and "the
# internet feels slow" arrived by human instead.
#
# 75 °C, not the SoC's own 80 °C cap. Assembled, navi peaked at 51.1 °C with all
# four cores pinned (navi.md), so anything near 75 is a regression in the
# cooling rather than a busy box, and an alarm that only fires at the cap is an
# alarm that fires after the throttling it was supposed to prevent.
#
# The since-boot throttle bits are deliberately NOT an alarm condition. They
# never clear until a reboot, so a monitor that alarmed on them would sit red
# for a fortnight over one bad afternoon and be ignored by the end of the first
# day. They ride along in the message instead, which is where the panel already
# puts them. What does alarm is the "right now" half: currently throttling, or
# currently under-voltage, which is the PSU rather than the heat.
TEMP_WARN=65   # also in www/index.html, where the tile turns amber on the same number
TEMP_ALARM=75  # and red on this one
if [ -n "$KUMA_PUSH_TEMP" ]; then
    tmilli=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
    thr=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
    # Validate before any arithmetic, same as host-status.sh: an unexpected
    # vcgencmd output would otherwise make $(( )) throw inside a script that
    # twelve other monitors depend on finishing.
    [[ "${thr:-}" =~ ^0[xX][0-9a-fA-F]+$ ]] || thr=""

    if [[ ! "${tmilli:-}" =~ ^-?[0-9]+$ ]]; then
        # A thermal zone that has stopped answering is not 0 °C, and reporting
        # it as a comfortable zero is the exact silent failure this box exists
        # to catch.
        push "$KUMA_PUSH_TEMP" down "cannot read the thermal zone" 0
    else
        c=$(( tmilli / 1000 ))
        tdec=$(awk -v m="$tmilli" 'BEGIN{printf "%.1f", m/1000}')
        note=""; hot_now=""
        if [ -z "$thr" ]; then
            note=" - throttle word unreadable"
        else
            tv=$(( thr ))
            (( tv & 0xF     )) && hot_now="yes"
            (( tv & 0xF0000 )) && note=" - throttled since boot, word $thr"
        fi

        if [ -n "$hot_now" ]; then
            # Bit 0 is under-voltage, which is the power supply sagging rather
            # than the case failing, and sends you to a different shelf.
            (( tv & 0x1 )) && note=" - UNDER-VOLTAGE, suspect the PSU before the cooling"
            push "$KUMA_PUSH_TEMP" down "THROTTLING NOW at ${tdec} °C, word ${thr}${note}" "$tdec"
        elif [ "$c" -ge "$TEMP_ALARM" ]; then
            push "$KUMA_PUSH_TEMP" down "${tdec} °C - cooling has regressed, cap is 80 °C${note}" "$tdec"
        elif [ "$c" -ge "$TEMP_WARN" ]; then
            push "$KUMA_PUSH_TEMP" up "${tdec} °C - warm, normal peak is 51${note}" "$tdec"
        else
            push "$KUMA_PUSH_TEMP" up "${tdec} °C${note}" "$tdec"
        fi
    fi
fi
