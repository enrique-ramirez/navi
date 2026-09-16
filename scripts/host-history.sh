#!/bin/bash
# Rolls the per-sample history host-status.sh appends into the charts behind
# each tile on the landing page, and deletes anything older than 90 days.
#
# Same architecture as everything else on that page: a timer writes static
# files, Caddy serves them, the browser reads them. The page can't ask for a
# range, a bucket size or a metric, because there is nothing listening to ask.
# Three fixed views instead:
#
#   day.json      last 24 hours, every sample (one per 28s)
#   week.json     last 7 days, 5-minute buckets
#   quarter.json  last 90 days, 1-hour buckets
#
# Every bucket carries its max as well as its average. An hourly average of
# temperature is a flat line that hides exactly the spike you opened the chart
# to find.
#
# Downtime is read from the samples themselves rather than from boot records.
# Uptime going backwards means navi rebooted, and the box was down from the last
# sample before it to the moment it booted - which catches a power cut, where
# the journal has no clean shutdown to show. A gap with no reboot means navi
# was up but host-status.timer wasn't sampling, and the page says that instead,
# because "down" and "not watching" send you to different places.
#
# Runs every 5 minutes. day and week are rebuilt each time (a couple of MB of
# CSV at most); quarter reads all 22 MB, so it's rebuilt only once an hour,
# which is also its bucket size.
set -u
HIST=/srv/data/history
OUT=/srv/data/www/history
KEEP_DAYS=90
mkdir -p "$HIST" "$OUT"

now=$(date +%s)

# --- retention ---------------------------------------------------------------
# By file name, not mtime: a restored or copied file keeps the day it's about.
# One day of slack so the 90-day view never starts on a half-deleted edge.
cutoff=$(date -d "@$(( now - (KEEP_DAYS + 1) * 86400 ))" +%F)
for f in "$HIST"/????-??-??.csv; do
    [ -e "$f" ] || continue
    d=$(basename "$f" .csv)
    [[ "$d" < "$cutoff" ]] && rm -f "$f"
done

# rollup NAME RANGE_SECONDS BUCKET_SECONDS
rollup() {
    local name=$1 range=$2 bucket=$3
    local since=$(( (now - range) / bucket * bucket ))
    local first; first=$(date -d "@$since" +%F)

    # Files are named by local date and each one only holds that day's samples,
    # so everything from the day `since` falls in onwards is enough. Rows before
    # `since` in that first file still get read: they seed the previous state,
    # so the first event in range is a real transition rather than a guess.
    local files=()
    for f in "$HIST"/????-??-??.csv; do
        [ -e "$f" ] || continue
        [[ "$(basename "$f" .csv)" < "$first" ]] || files+=("$f")
    done

    # mawk, not gawk, is what Debian ships: no bitwise ops, no strftime, no
    # length(array). Nothing below uses them.
    cat "${files[@]}" /dev/null 2>/dev/null | awk -F, \
        -v since="$since" -v bucket="$bucket" -v now="$now" -v gap=120 '
    function flush() {
        if (!n) return
        T = T sep cur;           N = N sep n
        TA = TA sep (tn ? sprintf("%.1f", tsum / tn) : "null")
        TM = TM sep (tn ? sprintf("%.1f", tmax) : "null")
        LA = LA sep sprintf("%.2f", lsum / n);  LM = LM sep sprintf("%.2f", lmax)
        MA = MA sep sprintf("%.1f", msum / n);  MM = MM sep sprintf("%.1f", mmax)
        D  = D  sep dlast
        RA = RA sep int(rxsum / n);  RM = RM sep rxmax
        XA = XA sep int(txsum / n);  XM = XM sep txmax
        TH = TH sep thr
        S  = S  sep (sn ? smax : "null")
        sep = ","
        n = 0; tsum = lsum = msum = rxsum = txsum = 0
        tmax = lmax = mmax = rxmax = txmax = -1; thr = 0; sn = 0; smax = 0; tn = 0
    }
    function down(a, b, kind) {
        if (a < since) a = since
        if (b <= a) return
        DN = DN dsep "[" a "," b ",\"" kind "\"]"; dsep = ","
    }
    function event(t, kind, who, detail) {
        ne++; EV[ne] = "[" t ",\"" kind "\",\"" who "\",\"" detail "\"]"
    }
    BEGIN { tmax = lmax = mmax = rxmax = txmax = -1; cur = -1; thr = sn = smax = tn = 0 }
    $1 !~ /^[0-9]+$/ || NF < 16 { next }
    {
        ts = $1 + 0; up = $13 + 0

        if (pts && ts >= since) {
            boot = ts - up
            if (up < pup)                 down(pts, boot, "down")
            else if (ts - pts > gap)      down(pts, ts, "unsampled")

            c = split($14, parts, "|")
            for (i = 1; i <= c; i++) {
                split(parts[i], f, ":")
                if (f[1] in cst) {
                    if (f[2] != cst[f[1]]) event(ts, "state", f[1], cst[f[1]] ">" f[2])
                    if (f[3] + 0 > crs[f[1]] + 0) event(ts, "restart", f[1], f[3] - crs[f[1]])
                }
            }
            c = split($15, parts, "|")
            for (i = 1; i <= c; i++) {
                split(parts[i], f, ":")
                if (f[1] in uac) {
                    if (f[2] != uac[f[1]]) event(ts, "timer", f[1], uac[f[1]] ">" f[2])
                    if (f[3] != ure[f[1]]) event(ts, "result", f[1], ure[f[1]] ">" f[3])
                }
            }
        }

        # Previous state is kept for every row, in range or not.
        c = split($14, parts, "|")
        for (i = 1; i <= c; i++) { split(parts[i], f, ":"); cst[f[1]] = f[2]; crs[f[1]] = f[3] }
        c = split($15, parts, "|")
        for (i = 1; i <= c; i++) { split(parts[i], f, ":"); uac[f[1]] = f[2]; ure[f[1]] = f[3] }
        pts = ts; pup = up

        if (ts < since) next

        b = int(ts / bucket) * bucket
        if (b != cur) { flush(); cur = b }
        n++
        if ($2 != "") { tn++; v = $2 + 0; tsum += v; if (v > tmax) tmax = v }
        v = $4 + 0;  lsum += v;  if (v > lmax) lmax = v
        v = ($9 > 0) ? $8 / $9 * 100 : 0;  msum += v;  if (v > mmax) mmax = v
        dlast = $10 + 0
        v = $11 + 0; rxsum += v; if (v > rxmax) rxmax = v
        v = $12 + 0; txsum += v; if (v > txmax) txmax = v
        # Bits 0-3 are "right now". No bitwise ops in mawk, but modulo does it.
        if (($3 + 0) % 16) thr = 1
        if ($16 != "") { sn++; if ($16 + 0 > smax) smax = $16 + 0 }
        cores = $7 + 0
    }
    END {
        flush()
        if (pts && now - pts > gap) down(pts, now, "unsampled")
        es = ""; for (i = (ne > 300 ? ne - 299 : 1); i <= ne; i++) { E = E es EV[i]; es = "," }
        printf "{\"generated\":%d,\"since\":%d,\"bucket\":%d,\"cores\":%d,\n", now, since, bucket, cores
        printf "\"t\":[%s],\n\"n\":[%s],\n", T, N
        printf "\"temp\":[%s],\n\"temp_max\":[%s],\n", TA, TM
        printf "\"load\":[%s],\n\"load_max\":[%s],\n", LA, LM
        printf "\"mem\":[%s],\n\"mem_max\":[%s],\n", MA, MM
        printf "\"disk\":[%s],\n", D
        printf "\"rx\":[%s],\n\"rx_max\":[%s],\n\"tx\":[%s],\n\"tx_max\":[%s],\n", RA, RM, XA, XM
        printf "\"throttled\":[%s],\n\"ssh\":[%s],\n", TH, S
        printf "\"down\":[%s],\n\"events\":[%s]}\n", DN, E
    }' > "$OUT/$name.json.tmp" || return

    chmod 644 "$OUT/$name.json.tmp"
    mv "$OUT/$name.json.tmp" "$OUT/$name.json"
}

rollup day 86400 1
rollup week $(( 7 * 86400 )) 300

# Also rebuilt whenever it holds no samples at all, or the first build after a
# deploy - which ran before there was anything to read - would leave the 90-day
# view saying "no samples" for its first hour.
q="$OUT/quarter.json"
if [ ! -f "$q" ] || [ $(( now - $(stat -c %Y "$q") )) -ge 3300 ] || grep -q '^"t":\[\],$' "$q"; then
    rollup quarter $(( KEEP_DAYS * 86400 )) 3600
fi
