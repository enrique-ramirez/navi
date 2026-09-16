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
# Same idea for the history CSV, where the separators are , | and : instead.
# Pure expansion, no forks: it runs eight times a sample.
h() { local v=${1:-}; v=${v//[^a-zA-Z0-9_.-]/_}; printf '%s' "${v:0:40}"; }

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
# Interface counters, not a speed test. A speed test on a timer would saturate
# the line it's measuring, every few minutes, forever, and the two ISP lines are
# already checked end to end by monitors 6 and 7. What isn't visible anywhere
# else is what this box is actually moving, which is the number that tells you
# whether "the internet is slow" is navi's doing.
#
# The rate is measured from the previous run's counters, not from two reads a
# couple of seconds apart. A 2-second window every 28 seconds sees 7% of the
# traffic and misses almost every burst, which was tolerable for a live tile and
# is useless for a history chart: the peaks are the part you wanted. Measured
# run to run, every byte lands in some sample.
#
# The 2-second read survives only as the fallback for the first run after a
# boot, or when the state is missing, stale, or from a counter that reset. A
# false zero on the page would look like navi went quiet.
IF=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
IF=${IF:-eth0}
S=/sys/class/net/$IF/statistics
NETSTATE=/srv/data/host-net.state
# Milliseconds, from bash's own clock rather than a `date` fork. At a 28-second
# period, whole seconds would put up to 7% of jitter into every rate.
ms() { local t=${EPOCHREALTIME/[.,]/}; echo $(( t / 1000 )); }
t2=$(ms)
rx2=$(cat "$S/rx_bytes" 2>/dev/null || echo 0)
tx2=$(cat "$S/tx_bytes" 2>/dev/null || echo 0)
pif=""; t1=0; rx1=0; tx1=0
[ -f "$NETSTATE" ] && read -r pif t1 rx1 tx1 < "$NETSTATE"
dt=$(( t2 - ${t1:-0} ))
if [ "$pif" != "$IF" ] || [ "$dt" -le 0 ] || [ "$dt" -gt 120000 ] \
   || [ "$rx2" -lt "${rx1:-0}" ] || [ "$tx2" -lt "${tx1:-0}" ]; then
    rx1=$rx2; tx1=$tx2; t1=$t2
    sleep 2
    t2=$(ms)
    rx2=$(cat "$S/rx_bytes" 2>/dev/null || echo 0)
    tx2=$(cat "$S/tx_bytes" 2>/dev/null || echo 0)
    dt=$(( t2 - t1 )); [ "$dt" -le 0 ] && dt=1
fi
printf '%s %s %s %s\n' "$IF" "$t2" "$rx2" "$tx2" > "$NETSTATE"
# Clamp anyway: a counter can still reset between the check and the read, and a
# negative rate rendered as a download speed looks like corruption.
rxbps=$(( (rx2 - rx1) * 1000 / dt )); [ "$rxbps" -lt 0 ] && rxbps=0
txbps=$(( (tx2 - tx1) * 1000 / dt )); [ "$txbps" -lt 0 ] && txbps=0
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

svcs=""; hsvcs=""
for c in $CONTAINERS; do
    state=missing; restarts=0
    while read -r name st rc; do
        [ "${name#/}" = "$c" ] || continue
        state=$st; restarts=$rc; break
    done <<< "$dockout"
    svcs="$svcs,{\"name\":\"$c\",\"state\":\"$(j "$state")\",\"restarts\":${restarts:-0}}"
    hsvcs="$hsvcs|$c:$(h "$state"):${restarts:-0}"
done

# --- timers ------------------------------------------------------------------
# wan-check dying is loud, because six push monitors go stale and Kuma shouts.
# The other two are silent: nothing anywhere notices if the nightly backup has
# been failing for a month. That gap is most of the reason this file exists.
units=""; hunits=""
for u in wan-check navi-backup repo-status host-status host-history; do
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
    hunits="$hunits|$u:$(h "$active"):$(h "${result:-unknown}")"
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

# --- history -----------------------------------------------------------------
#
# The same sample, appended as one CSV line to a file per day. host-history.sh
# rolls these up into the charts behind each tile and deletes days past 90.
#
# A file per day rather than one growing file, so retention is deleting old
# files instead of rewriting a live one, and a torn write at power loss costs
# at most one line of one day. Roughly 250 KB a day, 22 MB for the full 90.
#
# Deliberately not in /srv/data/www. The page gets the rollups, not the raw log.
#
# Columns, in order. Append new ones at the END only: host-history.sh reads by
# position, and 90 days of old files will still have the old width.
#   1 epoch s    2 temp C (empty = unreadable)     3 throttle word (decimal)  4-6 load 1/5/15
#   7 cores      8 mem used kB  9 mem total kB  10 disk %  11 rx B/s  12 tx B/s
#   13 uptime s  14 containers name:state:restarts|...
#   15 timers name:timer:result|...   16 rejected SSH in 24h (empty = unknown)
#
# Time only moves forward in here. A Pi has no real-time clock: after a power
# cut it boots on fake-hwclock's last save, up to an hour in the past, and stays
# there until NTP answers - which, after a power cut, can be a while, since the
# modems boot slower than navi does. Samples stamped in that window would land
# in the wrong day's file and make the rollup see time run backwards. Dropping
# them costs a couple of minutes of history right after a boot that's already
# being recorded as downtime.
HIST=/srv/data/history
LAST=/srv/data/host-history.last
mkdir -p "$HIST"
prev=$(cat "$LAST" 2>/dev/null); case "$prev" in ''|*[!0-9]*) prev=0 ;; esac
# fake-hwclock is never days behind. If the stored mark is, the mark is what's
# wrong (a clock that once jumped forward), and honouring it would stop history
# silently until real time caught up.
[ $(( prev - now )) -gt 172800 ] && prev=0
if [ "$now" -gt "$prev" ]; then
    sf=$sshfail; [ "$sf" = null ] && sf=""
    # The page's tile shows 0 for an unreadable sensor; a chart would draw that
    # as a plunge to 0 °C. Empty means unknown, and the chart leaves a gap.
    ht=$temp; [ -r /sys/class/thermal/thermal_zone0/temp ] || ht=""
    day="$HIST/$(date -d "@$now" +%F).csv"
    # A power cut mid-write leaves a line with no newline, and this sample would
    # be glued onto it. Finish the torn line first; the rollup skips it as short.
    [ -s "$day" ] && [ -n "$(tail -c1 "$day")" ] && echo >> "$day"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$now" "$ht" "$tv" "$l1" "$l5" "$l15" "$cores" "$(( mt - ma ))" "$mt" "${dpct:-0}" \
        "$rxbps" "$txbps" "$up" "${hsvcs#|}" "${hunits#|}" "$sf" \
        >> "$day"
    echo "$now" > "$LAST"
fi
