#!/bin/bash
# Samples this box's vitals: writes host.json and the log-<service>.json files
# the vitals page reads, and appends one CSV line per sample for host-history.sh.
#
# Where it runs: on the box it describes (hyrule-castle), as root, from
# host-status.timer every 28 s. Installed beside defaults.conf in
# /usr/local/lib/vitals. Root is needed for the whole journal and the systemd
# accounting counters.
#
# How it is invoked: no arguments. VITALS_CONF (default /etc/vitals.conf) and
# VITALS_DEFAULTS (default defaults.conf beside this script) name the config;
# VITALS_DATA (default /srv/data) moves every path this script writes, so a test
# can run under _tmp/. A config problem exits 1 with file:line on stderr.
#
# What it never touches: units, config, the music library, foobar2000's profile
# and the backups. It reads them. It writes only under $VITALS_DATA (www/,
# history/, logs/). Nothing here listens, so nothing on the LAN can make this
# script run. There is no docker and no python in the sample: the cost budget is
# 200 ms of CPU, so forks are counted, and what can be done with bash
# expansions is.
#
# Config is data, not shell: both files are read by whitelist and never sourced.
set -u
# Bytes, not characters: the console-log offsets below are byte counts.
export LC_ALL=C

DATA=${VITALS_DATA:-/srv/data}
WWW=$DATA/www
HIST=$DATA/history
LOGS=$DATA/logs
mkdir -p "$WWW" "$HIST" "$LOGS"

here=${0%/*}; [ "$here" = "$0" ] && here=.
DEFAULTS=${VITALS_DEFAULTS:-$here/defaults.conf}
CONF=${VITALS_CONF:-/etc/vitals.conf}

THRESH_KEYS="TEMP_WARN TEMP_BAD CPU_WARN CPU_BAD MEM_WARN MEM_BAD DISK_WARN DISK_BAD BACKUP_WARN_H BACKUP_BAD_H FAILED_WARN"
HOST=""; LABEL=""; UNITS=""; TIMERS=""; BACKUP_GLOB=""; SERVICES=""; RESTARTABLE=""
declare -A SVC_UNIT SVC_LOG SVC_EXTRA

load_conf() {
    local f=$1 n=0 k v name
    if [ ! -r "$f" ]; then
        echo "$f: cannot read config" >&2; exit 1
    fi
    while IFS='=' read -r k v || [ -n "$k" ]; do
        n=$(( n + 1 ))
        # Trailing whitespace and a CR (a file edited on Windows) are not part
        # of a key or a value. An indented comment is still a comment.
        k=${k#"${k%%[![:space:]]*}"}
        k=${k%"${k##*[![:space:]]}"}
        v=${v#"${v%%[![:space:]]*}"}
        v=${v%"${v##*[![:space:]]}"}
        [ -z "$k" ] && continue
        case "$k" in \#*) continue ;; esac
        case "$k" in
            TEMP_WARN|TEMP_BAD|CPU_WARN|CPU_BAD|MEM_WARN|MEM_BAD|DISK_WARN|DISK_BAD|BACKUP_WARN_H|BACKUP_BAD_H|FAILED_WARN)
                # No leading zero: 080 would reach host.json as invalid JSON.
                case "$v" in
                    ''|0?*|*[!0-9]*) echo "$f:$n: $k must be an integer" >&2; exit 1 ;;
                esac
                printf -v "$k" '%s' "$v" ;;
            SERVICES)
                # box is the box's own name in log-box.json, box.cursor,
                # box.lines and the 24 hour counts.
                for name in $v; do
                    if [ "$name" = box ]; then
                        echo "$f:$n: service name box is reserved" >&2; exit 1
                    fi
                done
                SERVICES=$v ;;
            HOST|LABEL|UNITS|TIMERS|BACKUP_GLOB|RESTARTABLE)
                printf -v "$k" '%s' "$v" ;;
            SERVICE_*_UNIT|SERVICE_*_LOG|SERVICE_*_EXTRA)
                name=${k#SERVICE_}; name=${name%_*}
                case "$name" in
                    ''|*[!a-z0-9]*) echo "$f:$n: unknown key $k" >&2; exit 1 ;;
                esac
                case "$k" in
                    *_UNIT)  SVC_UNIT[$name]=$v ;;
                    *_LOG)   SVC_LOG[$name]=$v ;;
                    *_EXTRA) SVC_EXTRA[$name]=$v ;;
                esac ;;
            *) echo "$f:$n: unknown key $k" >&2; exit 1 ;;
        esac
    done < "$f"
}
load_conf "$DEFAULTS"
load_conf "$CONF"
HOST=${HOST:-$HOSTNAME}

# Service names become file names under $LOGS, so a name that is not [a-z0-9]+
# stops the run rather than reaching a path.
for name in $SERVICES; do
    case "$name" in
        *[!a-z0-9]*) echo "$CONF: bad service name $name" >&2; exit 1 ;;
    esac
done

# These set a global instead of printing: $(f) forks a subshell, and several of
# them run for every unit, timer and log line.
#
# J: a value for a JSON string, with the two characters that break hand-built
# JSON removed. Used for names and states, which are not free text.
j() { local v=${1:-}; v=${v//[\"\\]/}; v=${v//[[:cntrl:]]/}; J=${v:0:120}; }
# ESC: free text (a log line) escaped for JSON, keeping its content. Capped so
# one runaway line cannot make the rolling file unreadable.
esc() { local v=${1:-}; v=${v:0:1000}; v=${v//[[:cntrl:]]/ }; v=${v//\\/\\\\}; v=${v//\"/\\\"}; ESC=$v; }
# H: a value for the history CSV, where the separators are , | : and =.
h() { local v=${1:-}; v=${v//[^a-zA-Z0-9_.-]/_}; H=${v:0:40}; }
isnum() { case "${1:-}" in ''|*[!0-9]*) return 1 ;; esac; }
# TENTHS: N is a count of tenths, TENTHS is "N/10" with one decimal.
tenths() { TENTHS="$(( $1 / 10 )).$(( $1 % 10 ))"; }
# Milliseconds from bash's own clock. At a 28 s period whole seconds would put
# up to 7% of jitter into every rate.
ms() { local t=${EPOCHREALTIME/[.,]/}; MS=$(( t / 1000 )); }
# ISO-8601 with a numeric offset, without forking date.
iso() { local z; printf -v ISO '%(%Y-%m-%dT%H:%M:%S)T' "$1"; printf -v z '%(%z)T' "$1"; ISO=$ISO${z:0:3}:${z:3}; }
# A systemd timestamp string ("Wed 2026-10-08 10:00:00 CEST", "n/a", "") as a
# JSON value in TSJ: a quoted ISO time, or null.
tsiso() {
    local o; TSJ=null
    case "${1:-}" in ''|n/a) return 0 ;; esac
    if o=$(date -Is -d "$1" 2>/dev/null) && [ -n "$o" ]; then TSJ="\"$o\""; fi
}
# Publish FILE.tmp as FILE. A rename is atomic, so a reader sees the old file or
# the new one and never half of either.
atomic() { local f=$1; chmod 644 "$f.tmp"; mv "$f.tmp" "$f"; }
# rd VAR FILE : read the first line of FILE into VAR, quietly. VAR is left empty
# when the file is missing or unreadable.
rd() { printf -v "$1" '%s' ""; { read -r "$1" < "$2"; } 2>/dev/null; }

printf -v now '%(%s)T' -1

# The sensor is found by what it says it is, never by its hwmonN number: those
# numbers are assigned in probe order and move between boots.
temp=null; temp_csv=""; tcrit=null
for d in /sys/class/hwmon/hwmon*; do
    rd nm "$d/name"
    [ "$nm" = coretemp ] || continue
    for lf in "$d"/temp*_label; do
        rd lab "$lf"
        [ "$lab" = "Package id 0" ] || continue
        base=${lf%_label}
        rd raw "${base}_input"
        if isnum "$raw"; then
            printf -v temp '%d.%d' $(( raw / 1000 )) $(( (raw % 1000) / 100 ))
            temp_csv=$temp
        fi
        rd craw "${base}_crit"
        if isnum "$craw" && [ "$craw" -gt 0 ]; then tcrit=$(( craw / 1000 )); fi
        break 2
    done
done

# Throttle events since boot. The package counter is preferred: it is the one
# that says the whole CPU was throttled. Every logical CPU's directory shows the
# same package counter, so the figure is the highest one seen, not the sum
# (a sum would read eight times the truth on this box). The per-core counter is
# the fallback where a kernel only exposes that. Neither present means null:
# the counter is "unavailable", not zero.
throttles=null; thr_csv=""
tfiles=(/sys/devices/system/cpu/cpu*/thermal_throttle/package_throttle_count)
[ -e "${tfiles[0]}" ] || tfiles=(/sys/devices/system/cpu/cpu*/thermal_throttle/core_throttle_count)
if [ -e "${tfiles[0]}" ]; then
    tmax=-1
    for f in "${tfiles[@]}"; do
        rd v "$f"
        isnum "$v" && [ "$v" -gt "$tmax" ] && tmax=$v
    done
    if [ "$tmax" -ge 0 ]; then throttles=$tmax; thr_csv=$tmax; fi
fi

read -r up _ < /proc/uptime;  up=${up%.*}
read -r l1 l5 l15 _ < /proc/loadavg
iso $(( now - up )); booted=$ISO

mt=0; ma=0
while read -r k v _; do
    case "$k" in MemTotal:) mt=$v ;; MemAvailable:) ma=$v ;; esac
done < /proc/meminfo

# / as navi reads it. /srv/music joins when it is its own mount, which is what
# `mountpoint -q` tests; on a box where it is just a folder of /, df would
# repeat the figures for / and the tile would double-count one filesystem.
dargs=(/)
mountpoint -q /srv/music 2>/dev/null && dargs+=(/srv/music)
dtotal=0; dused=0; dpct=0; music=null; music_csv=""; di=-1
while read -r _ dt du _ dp _; do
    if [ "$di" -lt 0 ]; then
        :  # header line
    elif [ "$di" -eq 0 ]; then
        dtotal=$dt; dused=$du; dpct=${dp%\%}
    else
        music="{\"total_kb\":$dt,\"used_kb\":$du,\"pct\":${dp%\%}}"; music_csv=${dp%\%}
    fi
    di=$(( di + 1 ))
done < <(df -Pk "${dargs[@]}" 2>/dev/null)

# Both rates are measured from the previous run's counters, not from two reads a
# couple of seconds apart. A 2-second window every 28 seconds sees 7% of the
# traffic and misses almost every burst, and the peaks are what a history chart
# is for. Measured run to run, every jiffy and every byte lands in some sample.
#
# The 2-second read survives only as the fallback when the state is missing,
# stale, or from a counter that reset: the first run after a boot. A false zero
# would look like the box went quiet. The wait is shared, so a boot costs two
# seconds, not four.
CPUSTATE=$LOGS/cpu.state
NETSTATE=$LOGS/net.state

declare -A ctot cbusy ptot pbusy
cpu_snap() {
    local name u n s i w q sq st _r
    ctot=(); cbusy=()
    # The cpu lines come first in /proc/stat; the intr line after them is long.
    while read -r name u n s i w q sq st _r; do
        case "$name" in cpu|cpu[0-9]*) ;; *) break ;; esac
        ctot[$name]=$(( u + n + s + i + w + q + sq + st ))
        cbusy[$name]=$(( u + n + s + q + sq + st ))
    done < /proc/stat
}

IF=""
read -r _ _ _ _ IF _ < <(ip -4 route show default 2>/dev/null)
IF=${IF:-eth0}
S=/sys/class/net/$IF/statistics
net_snap() {
    rd rx2 "$S/rx_bytes"; rd tx2 "$S/tx_bytes"
    isnum "$rx2" || rx2=0
    isnum "$tx2" || tx2=0
}

ms; t2=$MS
cpu_snap; net_snap

t1c=0
if [ -r "$CPUSTATE" ]; then
    while read -r a b c; do
        if [ "$a" = ms ]; then t1c=$b; else ptot[$a]=$b; pbusy[$a]=$c; fi
    done < "$CPUSTATE"
fi
pif=""; t1=0; rx1=0; tx1=0
[ -r "$NETSTATE" ] && read -r pif t1 rx1 tx1 < "$NETSTATE"
isnum "$t1" || t1=0; isnum "$rx1" || rx1=0; isnum "$tx1" || tx1=0
isnum "$t1c" || t1c=0

cpu_bad=0; net_bad=0
dtc=$(( t2 - t1c ))
if [ -z "${ptot[cpu]:-}" ] || [ "$dtc" -le 0 ] || [ "$dtc" -gt 120000 ]; then cpu_bad=1; fi
dt=$(( t2 - t1 ))
if [ "$pif" != "$IF" ] || [ "$dt" -le 0 ] || [ "$dt" -gt 120000 ] \
   || [ "$rx2" -lt "$rx1" ] || [ "$tx2" -lt "$tx1" ]; then net_bad=1; fi

if [ "$cpu_bad" -eq 1 ] || [ "$net_bad" -eq 1 ]; then
    if [ "$cpu_bad" -eq 1 ]; then
        ptot=(); pbusy=()
        for k in "${!ctot[@]}"; do ptot[$k]=${ctot[$k]}; pbusy[$k]=${cbusy[$k]}; done
        t1c=$t2
    fi
    if [ "$net_bad" -eq 1 ]; then rx1=$rx2; tx1=$tx2; t1=$t2; fi
    sleep 2
    ms; t2=$MS
    cpu_snap; net_snap
fi

# Save the state for the next run before computing, so a later failure in this
# script still leaves the baseline moved forward.
{
    echo "ms $t2"
    for k in "${!ctot[@]}"; do echo "$k ${ctot[$k]} ${cbusy[$k]}"; done
} > "$CPUSTATE"
printf '%s %s %s %s\n' "$IF" "$t2" "$rx2" "$tx2" > "$NETSTATE"

# Box busy share and the busiest core, in tenths of a percent.
cpu_box=0; cpu_core=0; cores=0
for k in "${!ctot[@]}"; do
    [ -n "${ptot[$k]:-}" ] || continue
    dtot=$(( ${ctot[$k]} - ${ptot[$k]} ))
    [ "$dtot" -gt 0 ] || continue
    pc=$(( (${cbusy[$k]} - ${pbusy[$k]}) * 1000 / dtot ))
    [ "$pc" -lt 0 ] && pc=0; [ "$pc" -gt 1000 ] && pc=1000
    if [ "$k" = cpu ]; then cpu_box=$pc; else [ "$pc" -gt "$cpu_core" ] && cpu_core=$pc; fi
done
for k in "${!ctot[@]}"; do [ "$k" != cpu ] && cores=$(( cores + 1 )); done
[ "$cores" -gt 0 ] || cores=1
tenths "$cpu_box"; cpu_pct=$TENTHS
tenths "$cpu_core"; cpu_core_pct=$TENTHS

# Clamp: a counter can still reset between the check and the read, and a
# negative rate rendered as a download speed looks like corruption.
dt=$(( t2 - t1 )); [ "$dt" -le 0 ] && dt=1
rxbps=$(( (rx2 - rx1) * 1000 / dt )); [ "$rxbps" -lt 0 ] && rxbps=0
txbps=$(( (tx2 - tx1) * 1000 / dt )); [ "$txbps" -lt 0 ] && txbps=0
rd link "/sys/class/net/$IF/speed"
isnum "$link" || link=0
rd oper "/sys/class/net/$IF/operstate"; oper=${oper:-unknown}

units_json=""; units_csv=""
for u in $UNITS; do
    ust=unknown; urs=0
    while IFS='=' read -r k v; do
        case "$k" in ActiveState) ust=$v ;; NRestarts) urs=$v ;; esac
    done < <(systemctl show "$u.service" -p ActiveState -p NRestarts 2>/dev/null)
    isnum "$urs" || urs=0
    j "$u"; ju=$J; j "$ust"
    units_json="$units_json,{\"name\":\"$ju\",\"state\":\"$J\",\"restarts\":$urs}"
    h "$u"; hu=$H; h "$ust"
    units_csv="$units_csv|$hu:$H:$urs"
done

# A timer dying is silent: nothing notices if the nightly backup has been
# failing for a month. Both service properties come in one call.
timers_json=""; timers_csv=""
for u in $TIMERS; do
    active=$(systemctl is-active "$u.timer" 2>/dev/null) || true
    active=${active:-unknown}
    result=unknown; ts=""
    while IFS='=' read -r k v; do
        case "$k" in Result) result=$v ;; ExecMainExitTimestamp) ts=$v ;; esac
    done < <(systemctl show "$u.service" -p Result -p ExecMainExitTimestamp 2>/dev/null)
    tsiso "$ts"
    j "$u"; ju=$J; j "$active"; ja=$J; j "${result:-unknown}"
    timers_json="$timers_json,{\"name\":\"$ju\",\"timer\":\"$ja\",\"result\":\"$J\",\"last\":$TSJ}"
    h "$u"; hu=$H; h "$active"; ha=$H; h "${result:-unknown}"
    timers_csv="$timers_csv|$hu:$ha:$H"
done

# Sessions open now and the last login. Rejected attempts are not counted here.
mapfile -t who_lines < <(who 2>/dev/null)
sessions=${#who_lines[@]}

last_user=null; last_from=null; last_at=null
while read -r -a lf; do
    case "${lf[0]:-}" in ''|reboot|shutdown|wtmp|btmp) continue ;; esac
    j "${lf[0]}"; last_user="\"$J\""
    # A console login has no host column, so field 3 is the timestamp and every
    # column after it shifts left. Detect that rather than reporting a date as
    # the address someone connected from.
    if [[ "${lf[2]:-}" == 20??-??-??T* ]]; then
        last_from='"console"'; j "${lf[2]:-}"; last_at="\"$J\""
    else
        j "${lf[2]:-?}"; last_from="\"$J\""; j "${lf[3]:-}"; last_at="\"$J\""
    fi
    break
done < <(last -w -n 20 --time-format=iso 2>/dev/null)
[ "$last_at" = '""' ] && last_at=null

bage=null; bsize=0; bcount=0
if [ -n "$BACKUP_GLOB" ]; then
    shopt -s nullglob
    bfiles=($BACKUP_GLOB)
    shopt -u nullglob
    if [ "${#bfiles[@]}" -gt 0 ]; then
        newest=${bfiles[0]}
        for f in "${bfiles[@]}"; do [ "$f" -nt "$newest" ] && newest=$f; done
        read -r bmt bsize < <(stat -c '%Y %s' "$newest")
        bage=$(( (now - bmt) / 60 ))
        bcount=${#bfiles[@]}
    fi
fi

# Every log is read incrementally. A journal read keeps its place in a cursor
# file, so each call returns only what is new since the previous sample.
#
# Rolling files in $LOGS hold the newest 50 lines of each log, newest last, one
# ready-made JSON object per line ({"t":..,"from":..,"text":..}). Escaping a
# line happens once, when it arrives. The log-*.json documents are made from
# these files by reversing them.

# jread CURSORFILE ARGS... : the new lines of `journalctl ARGS` in JV, only the
# ones that begin with a unix time.
#
# journalctl refuses --since together with --cursor-file, so a missing cursor is
# seeded instead of read through: the newest entry's cursor is written to the
# file and nothing is read this sample. The lines from before the seed are not
# wanted. If the journal has no entry for the filter yet, no cursor is written
# and the next sample tries again. From then on every read is --cursor-file alone.
#
# A non-zero exit is taken to mean a stale cursor (rotation or vacuum). The
# cursor is deleted and the next sample reseeds it, so a recovery drops the lines
# between the stale cursor and the reseed. journalctl's stderr is left to reach
# this script's, so a refusal shows in the journal of host-status.service.
jread() {
    local cur=$1 out rc l ts; shift
    JV=()
    if [ ! -e "$cur" ]; then
        out=$(journalctl "$@" -n 1 -q -o cat --no-pager --show-cursor)
        while IFS= read -r l; do
            case "$l" in
                "-- cursor: "?*) printf '%s\n' "${l#-- cursor: }" > "$cur" ;;
            esac
        done <<< "$out"
        return 0
    fi
    out=$(journalctl "$@" -o short-unix --no-pager -q --cursor-file="$cur")
    rc=$?
    if [ "$rc" -ne 0 ]; then
        rm -f "$cur"
        return 0
    fi
    while IFS= read -r l; do
        ts=${l%% *}
        [[ $ts =~ ^[0-9]+\.[0-9]+$ ]] && JV+=("$l")
    done <<< "$out"
}

# jparse LINE : P_T (epoch), P_FROM (program or unit), P_MSG of a short-unix line.
jparse() {
    local l=$1 rest
    P_T=${l%% *}; P_T=${P_T%%.*}
    rest=${l#* }; rest=${rest#* }
    case "$rest" in
        *": "*) P_FROM=${rest%%: *}; P_MSG=${rest#*: } ;;
        *)      P_FROM=""; P_MSG=$rest ;;
    esac
    P_FROM=${P_FROM%%\[*}
    case "$P_FROM" in ''|*" "*) P_FROM=unknown ;; esac
}

# frag T FROM TEXT : FRAG, one JSON object for a rolling file.
frag() {
    local t=$1 f
    esc "$2"; f=$ESC; esc "$3"
    FRAG="{\"t\":$t,\"from\":\"$f\",\"text\":\"$ESC\"}"
}

# roll FILE FRAG... : append to the rolling file, keep the newest 50.
roll() {
    local f=$1; shift
    local all=()
    [ -r "$f" ] && mapfile -t all < "$f"
    all+=("$@")
    if [ "${#all[@]}" -gt 50 ]; then all=("${all[@]: -50}"); fi
    if [ "${#all[@]}" -gt 0 ]; then printf '%s\n' "${all[@]}" > "$f.tmp"; else : > "$f.tmp"; fi
    atomic "$f"
}

# render_log OUT SOURCE LINESFILE [WRITESFILE] : the served JSON, newest first.
# A fragment that does not look whole (a file torn by a power cut) is dropped
# instead of breaking the document. Rewritten only when it changed.
render_log() {
    local out=$1 src=$2 lf=${3:-} wf=${4:-} doc body w i fr
    local a=()
    body=""
    if [ -n "$lf" ] && [ -r "$lf" ]; then
        mapfile -t a < "$lf"
        for (( i = ${#a[@]} - 1; i >= 0; i-- )); do
            fr=${a[i]}; [[ $fr == '{"t":'*'}' ]] && body="$body,$fr"
        done
    fi
    doc="{\"source\":\"$src\",\"lines\":[${body#,}]"
    if [ -n "$wf" ]; then
        w=""; a=()
        [ -r "$wf" ] && mapfile -t a < "$wf"
        for (( i = ${#a[@]} - 1; i >= 0; i-- )); do
            fr=${a[i]}; [[ $fr == '{"t":'*'}' ]] && w="$w,$fr"
        done
        doc="$doc,\"writes\":[${w#,}]"
    fi
    doc="$doc}"
    if [ -r "$out" ] && [ "$(< "$out")" = "$doc" ]; then return 0; fi
    printf '%s\n' "$doc" > "$out.tmp"
    atomic "$out"
}

# The box: every journal line at priority err or worse, from any unit.
jread "$LOGS/box.cursor" -p err
errs=${#JV[@]}; last_err=0
if [ "$errs" -gt 0 ]; then
    jparse "${JV[errs-1]}"; last_err=$P_T
    start=$(( errs > 50 ? errs - 50 : 0 ))
    fr=()
    for (( i = start; i < errs; i++ )); do
        jparse "${JV[i]}"; frag "$P_T" "$P_FROM" "$P_MSG"; fr+=("$FRAG")
    done
    roll "$LOGS/box.lines" "${fr[@]}"
fi
render_log "$WWW/log-box.json" journal "$LOGS/box.lines"

# counts.state has one line per sample and owner: `epoch owner a b last`. The
# owner is `box` (a = err lines, b unused) or a service name (a = write lines,
# b = failed write lines).
#
# `last` is the newest matching line's epoch ever seen, kept in $LOGS/last-<owner>
# because a quiet day empties the counts file of every line that had one. Every
# sample writes the larger of that file and its own newest line, so "how long
# ago" survives.
COUNTS=$LOGS/counts.state
# carry_last OWNER EPOCH : CARRIED, the newest epoch seen for OWNER so far.
carry_last() {
    local f=$LOGS/last-$1 prev
    rd prev "$f"; isnum "$prev" || prev=0
    CARRIED=$prev
    if [ "$2" -gt "$prev" ]; then CARRIED=$2; echo "$2" > "$f"; fi
}
carry_last box "$last_err"
counts_lines=("$now box $errs 0 $CARRIED")

declare -A svc_head svc_csv svc_extra_json wthis fthis
tz_off=0
printf -v z '%(%z)T' "$now"
case "$z" in
    -*) tz_off=$(( -(10#${z:1:2} * 3600 + 10#${z:3:2} * 60) )) ;;
    *)  tz_off=$(( 10#${z:1:2} * 3600 + 10#${z:3:2} * 60 )) ;;
esac

# ltime LINE : T, the epoch of a console-log line, or null. Only a line that
# starts "YYYY-MM-DD HH:MM:SS" or "HH:MM:SS" has one. A bare time takes today's
# date, or yesterday's when that would land in the future.
ltime() {
    local l=$1 y m d hh mm ss era yoe doy doe days
    T=null
    case "$l" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]" "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*)
            y=$((10#${l:0:4})); m=$((10#${l:5:2})); d=$((10#${l:8:2}))
            hh=$((10#${l:11:2})); mm=$((10#${l:14:2})); ss=$((10#${l:17:2}))
            [ "$m" -le 2 ] && y=$(( y - 1 ))
            era=$(( y / 400 )); yoe=$(( y - era * 400 ))
            doy=$(( (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1 ))
            doe=$(( yoe * 365 + yoe / 4 - yoe / 100 + doy ))
            days=$(( era * 146097 + doe - 719468 ))
            T=$(( days * 86400 + hh * 3600 + mm * 60 + ss - tz_off )) ;;
        [0-9][0-9]:[0-9][0-9]:[0-9][0-9]*)
            local nh nm ns mid
            printf -v nh '%(%H)T' "$now"; printf -v nm '%(%M)T' "$now"; printf -v ns '%(%S)T' "$now"
            mid=$(( now - 10#$nh * 3600 - 10#$nm * 60 - 10#$ns ))
            T=$(( mid + 10#${l:0:2} * 3600 + 10#${l:3:2} * 60 + 10#${l:6:2} ))
            [ "$T" -gt $(( now + 60 )) ] && T=$(( T - 86400 )) ;;
    esac
}

for name in $SERVICES; do
    unit=${SVC_UNIT[$name]:-$name.service}
    logspec=${SVC_LOG[$name]:-off}
    extra=${SVC_EXTRA[$name]:-}

    st=unknown; since=""; nr=0; res=unknown; cpuns=""; memc=""; memp=""
    while IFS='=' read -r k v; do
        case "$k" in
            ActiveState) st=$v ;;
            ActiveEnterTimestamp) since=$v ;;
            NRestarts) nr=$v ;;
            Result) res=$v ;;
            CPUUsageNSec) cpuns=$v ;;
            MemoryCurrent) memc=$v ;;
            MemoryPeak) memp=$v ;;
        esac
    done < <(systemctl show "$unit" -p ActiveState -p ActiveEnterTimestamp -p NRestarts -p Result \
                -p CPUUsageNSec -p MemoryCurrent -p MemoryPeak 2>/dev/null)
    ms; tsv=$MS
    isnum "$nr" || nr=0
    tsiso "$since"; since_json=$TSJ

    # Inactive means unknown, never zero. [not set] (accounting off, or a
    # systemd without MemoryPeak) is not a number and so also becomes null.
    cpu=null; cpu_csv=""; mem=null; mem_csv=""; peak=null
    SST=$LOGS/svc-$name.state
    if [ "$st" = active ]; then
        if isnum "$memc"; then mem=$memc; mem_csv=$memc; fi
        if isnum "$memp"; then peak=$memp; fi
        if isnum "$cpuns"; then
            pms=0; pns=0
            [ -r "$SST" ] && read -r pms pns < "$SST"
            isnum "$pms" || pms=0; isnum "$pns" || pns=0
            dms=$(( tsv - pms )); dns=$(( cpuns - pns ))
            # A restart resets the counter, so a negative delta is no sample.
            if [ "$pms" -gt 0 ] && [ "$dms" -gt 0 ] && [ "$dms" -le 120000 ] && [ "$dns" -ge 0 ]; then
                tenths $(( (dns + dms * 500) / (dms * 1000) ))
                cpu=$TENTHS; cpu_csv=$TENTHS
            fi
            echo "$tsv $cpuns" > "$SST"
        else
            rm -f "$SST"
        fi
    else
        rm -f "$SST"
    fi

    restartable=false
    for r in $RESTARTABLE; do [ "$r" = "$name" ] && restartable=true; done

    logkind=off; extra_json="{}"; extra_csv=""
    LJSON=$WWW/log-$name.json
    case "$logspec" in
        journal)
            logkind=journal
            jread "$LOGS/$name.cursor" -u "$unit"
            total=${#JV[@]}; start=$(( total > 50 ? total - 50 : 0 ))
            nw=0; nf=0; last_w=0; lfr=(); wfr=()
            for (( i = 0; i < total; i++ )); do
                jparse "${JV[i]}"
                if [ "$i" -ge "$start" ]; then frag "$P_T" "$P_FROM" "$P_MSG"; lfr+=("$FRAG"); fi
                if [ "$extra" = writes ]; then
                    case "$P_MSG" in
                        "write "*)
                            nw=$(( nw + 1 )); last_w=$P_T
                            case "$P_MSG" in *" failed: "*) nf=$(( nf + 1 )) ;; esac
                            frag "$P_T" "$P_FROM" "$P_MSG"; wfr+=("$FRAG") ;;
                    esac
                fi
            done
            [ "$total" -gt 0 ] && roll "$LOGS/$name.lines" "${lfr[@]}"
            if [ "$extra" = writes ]; then
                [ "$nw" -gt 0 ] && roll "$LOGS/$name.writes" "${wfr[@]}"
                render_log "$LJSON" journal "$LOGS/$name.lines" "$LOGS/$name.writes"
            else
                render_log "$LJSON" journal "$LOGS/$name.lines"
            fi ;;
        file:*)
            dir=${logspec#file:}
            newest=""
            for f in "$dir"/*; do
                [ -f "$f" ] || continue
                if [ -z "$newest" ] || [ "$f" -nt "$newest" ]; then newest=$f; fi
            done
            OFFF=$LOGS/$name.offset
            if [ -z "$newest" ]; then
                rm -f "$OFFF" "$LOGS/$name.lines" "$LOGS/$name.writes" "$LOGS/$name.cursor"
                render_log "$LJSON" off
            else
                logkind=file
                poff=0; pfile=""
                [ -r "$OFFF" ] && read -r poff pfile < "$OFFF"
                isnum "$poff" || poff=0
                fsize=$(stat -c %s "$newest" 2>/dev/null); isnum "$fsize" || fsize=0
                skip=0
                # A different file, or one that shrank, is read afresh. A file
                # met for the first time is read from its last 32 KB, so a long
                # session's log is not parsed in bash on the first sample.
                if [ "$pfile" != "$newest" ] || [ "$fsize" -lt "$poff" ]; then
                    rm -f "$LOGS/$name.lines"
                    poff=0
                    if [ "$fsize" -gt 32768 ]; then poff=$(( fsize - 32768 )); skip=1; fi
                fi
                if [ "$fsize" -gt "$poff" ]; then
                    chunk=$(tail -c +$(( poff + 1 )) "$newest" 2>/dev/null; echo x)
                    chunk=${chunk%x}
                    # Only whole lines are consumed. A line the writer has not
                    # finished is read next sample, from its start.
                    tailpart=${chunk##*$'\n'}
                    whole=${chunk%"$tailpart"}
                    poff=$(( poff + ${#whole} ))
                    [ "$skip" -eq 1 ] && whole=${whole#*$'\n'}
                    if [ -n "$whole" ]; then
                        mapfile -t flines <<< "${whole%$'\n'}"
                        total=${#flines[@]}; start=$(( total > 50 ? total - 50 : 0 ))
                        lfr=()
                        for (( i = start; i < total; i++ )); do
                            l=${flines[i]%$'\r'}
                            [ -n "$l" ] || continue
                            ltime "$l"; frag "$T" "$name" "$l"; lfr+=("$FRAG")
                        done
                        [ "${#lfr[@]}" -gt 0 ] && roll "$LOGS/$name.lines" "${lfr[@]}"
                    fi
                fi
                echo "$poff $newest" > "$OFFF"
                render_log "$LJSON" file "$LOGS/$name.lines"
            fi ;;
        *)
            # Off forgets the journal place too: a later switch back to journal
            # would otherwise read the whole backlog into one sample.
            rm -f "$LOGS/$name.lines" "$LOGS/$name.writes" "$LOGS/$name.cursor" "$LOGS/$name.offset"
            render_log "$LJSON" off ;;
    esac

    case "$extra" in
        writes)
            # nw and nf are zero where the log is not the journal.
            [ "$logspec" = journal ] || { nw=0; nf=0; last_w=0; }
            carry_last "$name" "$last_w"
            counts_lines+=("$now $name $nw $nf $CARRIED")
            wthis[$name]=$nw; fthis[$name]=$nf ;;
        unplayable:*)
            upath=${extra#unplayable:}
            # Distinct lines that look like a path. The log repeats itself once per
            # start, and a line with no slash is not a file. An unreadable log is
            # null in host.json and absent from the CSV field (an empty value
            # would roll up as zero), never 0.
            nu=""
            [ -r "$upath" ] && nu=$(awk 'index($0, "/") || index($0, "\\") { if (!s[$0]++) n++ } END { print n + 0 }' "$upath" 2>/dev/null)
            if isnum "$nu"; then
                extra_json="{\"unplayable\":$nu}"; extra_csv=":unplayable=$nu"
            else
                extra_json="{\"unplayable\":null}"
            fi ;;
    esac

    j "$name"; jn=$J; j "$unit"; ju=$J; j "$st"; jst=$J; j "$res"; jres=$J
    svc_head[$name]="{\"name\":\"$jn\",\"unit\":\"$ju\",\"state\":\"$jst\",\"since\":$since_json,\"restarts\":$nr,\"result\":\"$jres\",\"cpu_pct\":$cpu,\"mem_bytes\":$mem,\"mem_peak_bytes\":$peak,\"restartable\":$restartable,\"log\":\"$logkind\""
    h "$name"
    svc_csv[$name]="$H:$cpu_csv:$mem_csv$extra_csv"
    svc_extra_json[$name]=$extra_json
done

printf '%s\n' "${counts_lines[@]}" >> "$COUNTS"
declare -A c_a c_b c_l
while read -r o a b l; do
    c_a[$o]=$a; c_b[$o]=$b; c_l[$o]=$l
done < <(awk -v cut="$(( now - 86400 ))" -v out="$COUNTS.tmp" '
    NF == 5 && $1 ~ /^[0-9]+$/ && $1 >= cut {
        print > out
        a[$2] += $3; b[$2] += $4; if ($5 + 0 > l[$2] + 0) l[$2] = $5; seen[$2] = 1
    }
    END { for (o in seen) print o, a[o], b[o], l[o] + 0 }' "$COUNTS")
[ -e "$COUNTS.tmp" ] && atomic "$COUNTS"

err24=${c_a[box]:-0}; err_last=${c_l[box]:-0}
if [ "${err_last:-0}" -gt 0 ]; then iso "$err_last"; err_at="\"$ISO\""; else err_at=null; fi

# The extras that need the 24 hour sums are filled in here, and the services are
# joined in config order. The CSV carries this sample's own write and failure
# counts, which the rollup sums per bucket.
services_json=""; services_csv=""
for name in $SERVICES; do
    sc=${svc_csv[$name]}
    if [ "${SVC_EXTRA[$name]:-}" = writes ]; then
        w24=${c_a[$name]:-0}; f24=${c_b[$name]:-0}; lw=${c_l[$name]:-0}
        if [ "${lw:-0}" -gt 0 ]; then iso "$lw"; lwj="\"$ISO\""; else lwj=null; fi
        ej="{\"writes_24h\":$w24,\"failed_24h\":$f24,\"last_at\":$lwj}"
        sc="$sc:writes=${wthis[$name]:-0}:failed=${fthis[$name]:-0}"
    else
        ej=${svc_extra_json[$name]}
    fi
    services_json="$services_json,${svc_head[$name]},\"extra\":$ej}"
    services_csv="$services_csv|$sc"
done

thresholds=""
for k in $THRESH_KEYS; do thresholds="$thresholds,\"$k\":${!k}"; done
j "$HOST"; jhost=$J; j "$LABEL"; jlabel=$J
j "$IF"; jif=$J; j "$oper"; joper=$J
iso "$now"; checked=$ISO

# Write to a temp file and rename. The server hands this out as it finds it, and
# a rename is atomic, so the page can never read half a document.
cat > "$WWW/host.json.tmp" <<JSON
{"checked":"$checked","host":"$jhost","label":"$jlabel",
 "thresholds":{${thresholds#,}},
 "temp_c":$temp,"temp_crit_c":$tcrit,"throttles":$throttles,
 "uptime_s":$up,"booted":"$booted",
 "load":[$l1,$l5,$l15],"cores":$cores,
 "cpu_pct":$cpu_pct,"cpu_core_max_pct":$cpu_core_pct,
 "mem_total_kb":$mt,"mem_avail_kb":$ma,
 "disk_total_kb":$dtotal,"disk_used_kb":$dused,"disk_pct":$dpct,
 "music":$music,
 "net":{"iface":"$jif","state":"$joper","link_mbit":$link,"rx_bps":$rxbps,"tx_bps":$txbps},
 "units":[${units_json#,}],
 "timers":[${timers_json#,}],
 "ssh":{"sessions":$sessions,"last_user":$last_user,"last_from":$last_from,"last_at":$last_at},
 "errors":{"count_24h":$err24,"last_at":$err_at},
 "backup":{"age_min":$bage,"size":$bsize,"count":$bcount},
 "services":[${services_json#,}]}
JSON
atomic "$WWW/host.json"

# The same sample, appended as one CSV line to a file per day. host-history.sh
# rolls these up into the charts behind each tile and deletes days past 90.
#
# A file per day rather than one growing file, so retention is deleting old
# files instead of rewriting a live one, and a torn write at power loss costs
# at most one line of one day.
#
# Columns, in order. Append new ones at the END only: host-history.sh reads by
# position, and 90 days of old files will still have the old width.
#   1 epoch s    2 temp C (empty = unreadable)    3 throttle events since boot
#   4-6 load 1/5/15    7 cores    8 mem used kB    9 mem total kB    10 disk % /
#   11 rx B/s    12 tx B/s    13 uptime s    14 units name:state:restarts|...
#   15 timers name:timer:result|...    16 cpu % box    17 cpu % busiest core
#   18 disk % /srv/music (empty = not a mount)    19 err lines since the last sample
#   20 services name:cpu_pct:mem_bytes:k=v:k=v|...    21 open SSH sessions
#
# Time only moves forward in here. A sample stamped before the last one written
# (the clock stepped back before NTP answered) would land in the wrong day's
# file and make the rollup see time run backwards, so it is dropped.
LAST=$LOGS/history.last
rd prev "$LAST"; isnum "$prev" || prev=0
# A mark days ahead of now is the thing that is wrong, and honouring it would
# stop history until real time caught up.
[ $(( prev - now )) -gt 172800 ] && prev=0
if [ "$now" -gt "$prev" ]; then
    printf -v day '%s/%(%Y-%m-%d)T.csv' "$HIST" "$now"
    # A power cut mid-write leaves a line with no newline, and this sample would
    # be glued onto it. Finish the torn line first; the rollup skips it as short.
    [ -s "$day" ] && [ -n "$(tail -c1 "$day")" ] && echo >> "$day"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$now" "$temp_csv" "$thr_csv" "$l1" "$l5" "$l15" "$cores" "$(( mt - ma ))" "$mt" "$dpct" \
        "$rxbps" "$txbps" "$up" "${units_csv#|}" "${timers_csv#|}" \
        "$cpu_pct" "$cpu_core_pct" "$music_csv" "$errs" "${services_csv#|}" "$sessions" \
        >> "$day"
    echo "$now" > "$LAST"
fi
