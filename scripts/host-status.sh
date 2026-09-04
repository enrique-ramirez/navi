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
#
# Runs every 28s against a page that polls every 30s. The offset is deliberate
# and host-status.timer explains it. Keep the two in step if you change either:
# a writer slower than the reader is the one arrangement that makes the panel
# consistently stale.
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
#
# One `docker inspect` for all three rather than one call each. The docker CLI
# is a large Go binary that has to start and connect to the daemon, and forking
# it is most of what this script costs; at a 28-second cadence that is the
# difference worth having. A container that doesn't exist is simply absent from
# the output (the call still succeeds for the others), which is how it ends up
# reported as missing rather than taking the whole block down with it.
CONTAINERS="pihole uptime-kuma caddy"
dockout=$(docker inspect --format '{{.Name}} {{.State.Status}} {{.RestartCount}}' \
          $CONTAINERS 2>/dev/null)

svcs=""
for c in $CONTAINERS; do
    state=missing; restarts=0
    while read -r name st rc; do
        [ "${name#/}" = "$c" ] || continue
        state=$st; restarts=$rc; break
    done <<< "$dockout"
    svcs="$svcs,{\"name\":\"$c\",\"state\":\"$(j "$state")\",\"restarts\":${restarts:-0}}"
done

# --- timers ------------------------------------------------------------------
# wan-check dying is loud, because six push monitors go stale and Kuma shouts.
# The other two are silent: nothing anywhere notices if the nightly backup has
# been failing for a month. That gap is most of the reason this file exists.
units=""
for u in wan-check navi-backup repo-status host-status; do
    active=$(systemctl is-active "$u.timer" 2>/dev/null || echo unknown)
    # Both properties in one call rather than two. Same parse-by-whitelist shape
    # as the /proc/meminfo read above and the .env read in wan-check.sh.
    result=unknown; ts=""
    while IFS='=' read -r k v; do
        case "$k" in Result) result=$v ;; ExecMainExitTimestamp) ts=$v ;; esac
    done < <(systemctl show "$u.service" -p Result -p ExecMainExitTimestamp 2>/dev/null)
    iso=null
    [ -n "$ts" ] && iso="\"$(date -Is -d "$ts" 2>/dev/null || echo "")\""
    [ "$iso" = '""' ] && iso=null
    units="$units,{\"name\":\"$u\",\"timer\":\"$(j "$active")\",\"result\":\"$(j "${result:-unknown}")\",\"last\":$iso}"
done

# --- SSH ---------------------------------------------------------------------
#
# Not a security control by itself: SSH is key-only and unreachable from outside
# the flat, so this is mostly a memory aid. Read next to the repo banner it
# answers the question that banner raises - the working tree is dirty because
# you were on the box on Tuesday and forgot.
#
# The rejected-attempt count is NOT computed here. wan-check.sh works it out
# every 5 minutes and leaves it in a file. A journalctl call is by a wide margin
# the most expensive thing this script could do, and a 24-hour count has no
# business being recomputed every 28 seconds.
sessions=$(who 2>/dev/null | wc -l); sessions=${sessions:-0}

last_user=null; last_from=null; last_at=null
line=$(last -w -n 20 --time-format=iso 2>/dev/null | grep -Ev '^(reboot|shutdown|wtmp|$)' | head -1)
if [ -n "$line" ]; then
    set -- $line
    last_user="\"$(j "$1")\""
    # A console login has no host column, so field 3 is the timestamp and every
    # column after it shifts left. Detect that rather than reporting a date as
    # the address someone connected from.
    if [ "${3:-}" != "${3#20??-??-??T}" ]; then
        last_from="\"console\""; last_at="\"$(j "${3:-}")\""
    else
        last_from="\"$(j "${3:-?}")\""; last_at="\"$(j "${4:-}")\""
    fi
fi
[ "$last_at" = '""' ] && last_at=null

# null, not 0, when the file is missing or stale. wan-check writes the literal
# string "unknown" when it can't read the journal, and that has to survive as
# "we don't know" rather than being rounded down to "nothing happened".
sshfail=null
SF=/srv/data/ssh-fail
if [ -f "$SF" ] && [ $(( now - $(stat -c %Y "$SF") )) -lt 900 ]; then
    v=$(cat "$SF" 2>/dev/null)
    case "$v" in ''|*[!0-9]*) sshfail=null ;; *) sshfail=$v ;; esac
fi

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
 "ssh":{"sessions":$sessions,"last_user":$last_user,"last_from":$last_from,"last_at":$last_at,"failed_24h":$sshfail},
 "backup":{"age_min":$bage,"size":$bsize,"count":$bcount}}
JSON
chmod 644 "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
