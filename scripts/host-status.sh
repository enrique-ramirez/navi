#!/bin/bash
# Writes this box's own vitals as JSON for the landing page.
#
# Same shape and same reasoning as repo-status.sh: a timer writes a static
# file, Caddy serves it, the page reads it. There is no endpoint, so there is
# no code path anything on the LAN can make this box execute. That rule is
# worth more here than it looks, because this script runs as root.
#
# Deliberately NOT a log tail. A journal excerpt on an unauthenticated LAN page
# is an information-disclosure surface that grows every time some service
# decides to log a token, and it isn't how you actually debug anything: you SSH
# in and read the whole unit. What's here instead is the derived half - is the
# timer alive, did the last run succeed, when - which is the part you want at a
# glance and which cannot leak a secret.
#
# Nothing here alerts. Uptime Kuma alerts. This is the page you read once
# something already told you to look.
set -u
OUT=/srv/data/www/host.json
mkdir -p "$(dirname "$OUT")"

# Strip the two characters that can break hand-built JSON. Same approach as
# repo-status.sh; nothing in here is attacker-controlled, this is for the
# docker status strings that occasionally contain punctuation.
j() { printf '%s' "${1:-}" | tr -d '"\\' | cut -c1-120; }

now=$(date +%s)

# --- temperature and throttling ----------------------------------------------
#
# The throttle word is the valuable half, not the temperature. Bits 0-3 are
# "right now", bits 16-19 are "has happened since boot", and the second set is
# the only record that a thermal or power problem occurred at 4am while nobody
# was looking. After the case and copper block went on this should read 0x0
# forever; if it ever doesn't, that's the regression.
temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
# An empty read here would emit "temp_c":, and the page would reject the whole
# document over one unreadable file.
temp=${temp:-0}

thr=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
# Validate before arithmetic: an unexpected vcgencmd output would otherwise make
# $(( )) throw, and a status page that dies on a malformed field is worse than
# one that reports 0x0 and a stale timestamp you can see.
thr=${thr:-0x0}
[[ "$thr" =~ ^0[xX][0-9a-fA-F]+$ ]] || thr=0x0
tv=$(( thr ))
now_flags=""; ever_flags=""
(( tv & 0x1     )) && now_flags="$now_flags,\"under-voltage\""
(( tv & 0x2     )) && now_flags="$now_flags,\"frequency capped\""
(( tv & 0x4     )) && now_flags="$now_flags,\"throttled\""
(( tv & 0x8     )) && now_flags="$now_flags,\"soft temp limit\""
(( tv & 0x10000 )) && ever_flags="$ever_flags,\"under-voltage\""
(( tv & 0x20000 )) && ever_flags="$ever_flags,\"frequency capped\""
(( tv & 0x40000 )) && ever_flags="$ever_flags,\"throttled\""
(( tv & 0x80000 )) && ever_flags="$ever_flags,\"soft temp limit\""

# --- uptime, load, memory ----------------------------------------------------
read -r up _ < /proc/uptime;  up=${up%.*}
read -r l1 l5 l15 _ < /proc/loadavg
cores=$(nproc 2>/dev/null || echo 1)
booted=$(date -Is -d "@$(( now - up ))" 2>/dev/null || echo "")

mt=0; ma=0
while read -r k v _; do
    case "$k" in MemTotal:) mt=$v ;; MemAvailable:) ma=$v ;; esac
done < /proc/meminfo

# --- disk --------------------------------------------------------------------
# Root only. /srv/data and /srv/backup are on it, and the 85% threshold matches
# the one wan-check.sh already alerts on - two different numbers for the same
# condition is how you end up trusting neither.
read -r dtotal dused dpct < <(df -Pk / | awk 'NR==2{print $2, $3, $5+0}')

# --- network throughput ------------------------------------------------------
#
# Interface counters sampled twice, not a speed test. A speed test on a timer
# would saturate the line it's measuring, every few minutes, forever, and the
# two ISP lines are already checked end to end by monitors 6 and 7. What isn't
# visible anywhere else is what this box is actually moving right now, which is
# the number that tells you whether "the internet is slow" is navi's doing.
IF=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
IF=${IF:-eth0}
S=/sys/class/net/$IF/statistics
rx1=$(cat "$S/rx_bytes" 2>/dev/null || echo 0)
tx1=$(cat "$S/tx_bytes" 2>/dev/null || echo 0)
sleep 2
rx2=$(cat "$S/rx_bytes" 2>/dev/null || echo 0)
tx2=$(cat "$S/tx_bytes" 2>/dev/null || echo 0)
# Clamp: counters reset when an interface bounces, and a negative rate rendered
# as a download speed looks like corruption rather than the reboot it was.
rxbps=$(( (rx2 - rx1) / 2 )); [ "$rxbps" -lt 0 ] && rxbps=0
txbps=$(( (tx2 - tx1) / 2 )); [ "$txbps" -lt 0 ] && txbps=0
link=$(cat "/sys/class/net/$IF/speed" 2>/dev/null || echo 0)
[ "${link:-0}" -lt 0 ] 2>/dev/null && link=0
oper=$(cat "/sys/class/net/$IF/operstate" 2>/dev/null || echo unknown)

# --- containers --------------------------------------------------------------
# RestartCount is the one worth having. A container that crashes and comes back
# inside a minute leaves nothing behind except this number going up, and a
# restarting Pi-hole is exactly the intermittent DNS nobody can reproduce.
svcs=""
for c in pihole uptime-kuma caddy; do
    st=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null || echo missing)
    rc=$(docker inspect -f '{{.RestartCount}}' "$c" 2>/dev/null || echo 0)
    svcs="$svcs,{\"name\":\"$c\",\"state\":\"$(j "$st")\",\"restarts\":${rc:-0}}"
done

# --- timers ------------------------------------------------------------------
# wan-check dying is loud, because six push monitors go stale and Kuma shouts.
# The other two are silent: nothing anywhere notices if the nightly backup has
# been failing for a month. That gap is most of the reason this file exists.
units=""
for u in wan-check navi-backup repo-status host-status; do
    active=$(systemctl is-active "$u.timer" 2>/dev/null || echo unknown)
    result=$(systemctl show "$u.service" -p Result --value 2>/dev/null || echo unknown)
    ts=$(systemctl show "$u.service" -p ExecMainExitTimestamp --value 2>/dev/null || echo "")
    iso=null
    [ -n "$ts" ] && iso="\"$(date -Is -d "$ts" 2>/dev/null || echo "")\""
    [ "$iso" = '""' ] && iso=null
    units="$units,{\"name\":\"$u\",\"timer\":\"$(j "$active")\",\"result\":\"$(j "${result:-unknown}")\",\"last\":$iso}"
done

# --- backup ------------------------------------------------------------------
bage=null; bsize=0; bcount=0
newest=$(ls -1t /srv/backup/navi-state-*.tar.gz 2>/dev/null | head -1)
if [ -n "$newest" ]; then
    bage=$(( ( now - $(stat -c %Y "$newest") ) / 60 ))
    bsize=$(stat -c %s "$newest")
    bcount=$(ls -1 /srv/backup/navi-state-*.tar.gz 2>/dev/null | wc -l)
fi

# Write to a temp file and rename. The page polls this every 60s and a rename is
# atomic, so it can never read half a JSON document and decide navi is broken.
cat > "$OUT.tmp" <<JSON
{"checked":"$(date -Is)",
 "temp_c":$temp,"throttled_hex":"$(j "$thr")",
 "throttled_now":[${now_flags#,}],"throttled_ever":[${ever_flags#,}],
 "uptime_s":$up,"booted":"$booted",
 "load":[$l1,$l5,$l15],"cores":$cores,
 "mem_total_kb":$mt,"mem_avail_kb":$ma,
 "disk_total_kb":${dtotal:-0},"disk_used_kb":${dused:-0},"disk_pct":${dpct:-0},
 "net":{"iface":"$(j "$IF")","state":"$(j "$oper")","link_mbit":${link:-0},"rx_bps":$rxbps,"tx_bps":$txbps},
 "services":[${svcs#,}],
 "units":[${units#,}],
 "backup":{"age_min":$bage,"size":$bsize,"count":$bcount}}
JSON
chmod 644 "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
