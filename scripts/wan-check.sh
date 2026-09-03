#!/bin/bash
# Pushes to Uptime Kuma's push monitors every 5 minutes via wan-check.timer.
#
# Covers the four things nothing else can see:
#   1. each ISP line, end to end and independently
#   2. Pi-hole actually blocking, not merely resolving
#   3. the blocklist still being fresh
#   4. whether a human needs to do something
set -u
source /srv/navi/.env

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
