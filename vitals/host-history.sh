#!/bin/bash
# Rolls the per-sample history host-status.sh appends into the charts behind
# each tile on the vitals page, and deletes anything older than 90 days.
#
# Where it runs: on the box it describes (hyrule-castle), as root, from
# host-history.timer every 5 minutes. Installed beside host-status.sh in
# /usr/local/lib/vitals.
#
# How it is invoked: no arguments. VITALS_DATA (default /srv/data) moves the
# folders it reads and writes, so a test can run it over fixture CSV files under
# _tmp/.
#
# What it never touches: the samples' source (it reads the CSV, not the system),
# the config, units and anything outside $VITALS_DATA/history and
# $VITALS_DATA/www/history. The only thing it deletes is a day's CSV past
# retention.
#
# The page cannot ask for a range, a bucket size or a metric, because the server
# only hands out files. Three fixed views instead:
#
#   day.json      last 24 hours, every sample (one per 28s)
#   week.json     last 7 days, 5-minute buckets
#   quarter.json  last 90 days, 1-hour buckets
#
# Every bucket carries its max as well as its average. An hourly average of
# temperature is a flat line that hides exactly the spike you opened the chart
# to find. Counts (errors, and each service's writes and failures) are summed
# per bucket instead, with the bucket's maximum next to them.
#
# Service names, and the k=v extras in CSV column 20, are read from the data. A
# box with another service needs no change here: every k gets a series `k` (sum
# per bucket) and `k_max`, and the page reads the ones that make sense for it.
#
# Downtime is read from the samples themselves rather than from boot records.
# Uptime going backwards means the box rebooted, and it was down from the last
# sample before it to the moment it booted, which catches a power cut where the
# journal has no clean shutdown to show. A gap with no reboot means the box was
# up but host-status.timer wasn't sampling, and the page says that instead,
# because "down" and "not watching" send you to different places.
#
# day and week are rebuilt each run. quarter reads all 90 days of CSV, so it is
# rebuilt once an hour, which is also its bucket size.
set -u
DATA=${VITALS_DATA:-/srv/data}
HIST=$DATA/history
OUT=$DATA/www/history
KEEP_DAYS=90
mkdir -p "$HIST" "$OUT"

now=$(date +%s)

# Local YYYY-MM-DD of an epoch, and a file's mtime. GNU date and stat on the
# box. The BSD forms are the fallback only so the rollup can be run over fixture
# files on a Mac.
day_of() { date -d "@$1" +%F 2>/dev/null || date -r "$1" +%F; }
mtime_of() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }

# By file name, not mtime: a restored or copied file keeps the day it's about.
# One day of slack so the 90-day view never starts on a half-deleted edge.
cutoff=$(day_of $(( now - (KEEP_DAYS + 1) * 86400 )))
for f in "$HIST"/????-??-??.csv; do
    [ -e "$f" ] || continue
    d=$(basename "$f" .csv)
    [[ "$d" < "$cutoff" ]] && rm -f "$f"
done

# rollup NAME RANGE_SECONDS BUCKET_SECONDS
rollup() {
    local name=$1 range=$2 bucket=$3
    local since=$(( (now - range) / bucket * bucket ))
    local first; first=$(day_of "$since")

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
    cat ${files[@]+"${files[@]}"} /dev/null 2>/dev/null | awk -F, \
        -v since="$since" -v bucket="$bucket" -v now="$now" -v gap=120 '
    # One bucket becomes one entry in every series. The top-level series are
    # strings that grow by a comma each flush; the per-service ones are held by
    # bucket number in SV, because a service can first appear in the middle of
    # the range and its earlier buckets must read null.
    function flush(   si, nm, ki, k) {
        if (!n) return
        bi++
        T = T sep cur;           N = N sep n
        TA = TA sep (tn ? sprintf("%.1f", tsum / tn) : "null")
        TM = TM sep (tn ? sprintf("%.1f", tmax) : "null")
        LA = LA sep sprintf("%.2f", lsum / n);  LM = LM sep sprintf("%.2f", lmax)
        CA = CA sep (cn ? sprintf("%.1f", csum / cn) : "null")
        CM = CM sep (cn ? sprintf("%.1f", cmax) : "null")
        CC = CC sep (ccn ? sprintf("%.1f", ccmax) : "null")
        MA = MA sep sprintf("%.1f", msum / n);  MM = MM sep sprintf("%.1f", mmax)
        D  = D  sep dlast
        MU = MU sep (mus ? mulast : "null")
        RA = RA sep int(rxsum / n);  RM = RM sep rxmax
        XA = XA sep int(txsum / n);  XM = XM sep txmax
        TH = TH sep (ths ? thmax : "null")
        SS = SS sep (sss ? sshmax : "null")
        ER = ER sep errsum
        sep = ","
        for (si = 1; si <= SN; si++) {
            nm = SNAME[si]
            if (SCN[nm]) {
                SV[nm, "cpu", bi] = sprintf("%.1f", SCS[nm] / SCN[nm])
                SV[nm, "cpu_max", bi] = sprintf("%.1f", SCM[nm])
            }
            if (SMN[nm]) {
                SV[nm, "mem", bi] = sprintf("%.1f", SMS[nm] / SMN[nm])
                SV[nm, "mem_max", bi] = sprintf("%.1f", SMM[nm])
            }
            SCS[nm] = 0; SCN[nm] = 0; SCM[nm] = 0; SMS[nm] = 0; SMN[nm] = 0; SMM[nm] = 0
            for (ki = 1; ki <= NK[nm]; ki++) {
                k = KN[nm, ki]
                if (KC[nm, k]) {
                    SV[nm, k, bi] = sprintf("%.0f", KS[nm, k])
                    SV[nm, k "_max", bi] = sprintf("%.0f", KM[nm, k])
                }
                KS[nm, k] = 0; KC[nm, k] = 0; KM[nm, k] = 0
            }
        }
        n = 0; tsum = lsum = msum = rxsum = txsum = csum = errsum = 0
        tmax = lmax = mmax = rxmax = txmax = -1
        cmax = ccmax = thmax = -1
        tn = cn = ccn = mus = ths = sss = 0; sshmax = -1
    }
    function series(nm, key,   bj, s, sp) {
        s = ""; sp = ""
        for (bj = 1; bj <= bi; bj++) {
            s = s sp (((nm, key, bj) in SV) ? SV[nm, key, bj] : "null"); sp = ","
        }
        return s
    }
    function down(a, b, kind) {
        if (a < since) a = since
        if (b <= a) return
        DN = DN dsep "[" a "," b ",\"" kind "\"]"; dsep = ","
    }
    function event(t, kind, who, detail) {
        ne++; EV[ne] = "[" t ",\"" kind "\",\"" who "\",\"" detail "\"]"
    }
    BEGIN {
        tmax = lmax = mmax = rxmax = txmax = cmax = ccmax = thmax = sshmax = -1; cur = -1
        tn = cn = ccn = mus = ths = sss = 0
    }
    # A row narrower than 20 columns predates a column or was torn by a power
    # cut. It is skipped whole rather than guessed at.
    $1 !~ /^[0-9]+$/ || NF < 20 { next }
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
        if ($16 != "") { cn++; v = $16 + 0; csum += v; if (v > cmax) cmax = v }
        if ($17 != "") { ccn++; v = $17 + 0; if (v > ccmax) ccmax = v }
        v = ($9 > 0) ? $8 / $9 * 100 : 0;  msum += v;  if (v > mmax) mmax = v
        dlast = $10 + 0
        if ($18 != "") { mus = 1; mulast = $18 + 0 }
        v = $11 + 0; rxsum += v; if (v > rxmax) rxmax = v
        v = $12 + 0; txsum += v; if (v > txmax) txmax = v
        # A counter since boot, so the bucket keeps its highest reading.
        if ($3 != "") { ths = 1; v = $3 + 0; if (v > thmax) thmax = v }
        errsum += $19 + 0
        # Column 21 arrived after the first samples were written: a 20-column
        # row rolls up with no SSH figure instead of being skipped.
        if ($21 != "") { sss = 1; v = $21 + 0; if (v > sshmax) sshmax = v }
        cores = $7 + 0

        # name:cpu_pct:mem_bytes:k=v:k=v, one per service. Empty cpu and memory
        # mean the unit was not active, so they add nothing to the averages.
        c = split($20, parts, "|")
        for (i = 1; i <= c; i++) {
            m = split(parts[i], f, ":")
            nm = f[1]
            if (nm == "") continue
            if (!(nm in SKNOWN)) { SKNOWN[nm] = 1; SN++; SNAME[SN] = nm }
            if (f[2] != "") { v = f[2] + 0; SCS[nm] += v; SCN[nm]++; if (v > SCM[nm]) SCM[nm] = v }
            if (f[3] != "") { v = f[3] / 1048576; SMS[nm] += v; SMN[nm]++; if (v > SMM[nm]) SMM[nm] = v }
            for (q = 4; q <= m; q++) {
                e = index(f[q], "=")
                if (e < 2) continue
                k = substr(f[q], 1, e - 1); v = substr(f[q], e + 1) + 0
                if (!((nm, k) in KSEEN)) { KSEEN[nm, k] = 1; NK[nm]++; KN[nm, NK[nm]] = k }
                KS[nm, k] += v; KC[nm, k]++; if (v > KM[nm, k]) KM[nm, k] = v
            }
        }
    }
    END {
        flush()
        if (pts && now - pts > gap) down(pts, now, "unsampled")
        es = ""; for (i = (ne > 300 ? ne - 299 : 1); i <= ne; i++) { E = E es EV[i]; es = "," }
        printf "{\"generated\":%d,\"since\":%d,\"bucket\":%d,\"cores\":%d,\n", now, since, bucket, cores
        printf "\"t\":[%s],\n\"n\":[%s],\n", T, N
        printf "\"temp\":[%s],\n\"temp_max\":[%s],\n", TA, TM
        printf "\"load\":[%s],\n\"load_max\":[%s],\n", LA, LM
        printf "\"cpu\":[%s],\n\"cpu_max\":[%s],\n\"cpu_core_max\":[%s],\n", CA, CM, CC
        printf "\"mem\":[%s],\n\"mem_max\":[%s],\n", MA, MM
        printf "\"disk\":[%s],\n\"music\":[%s],\n", D, MU
        printf "\"rx\":[%s],\n\"rx_max\":[%s],\n\"tx\":[%s],\n\"tx_max\":[%s],\n", RA, RM, XA, XM
        printf "\"throttles\":[%s],\n\"errors\":[%s],\n\"ssh\":[%s],\n", TH, ER, SS
        printf "\"services\":{"
        for (si = 1; si <= SN; si++) {
            nm = SNAME[si]
            printf "%s\"%s\":{\"cpu\":[%s],\"cpu_max\":[%s],\"mem\":[%s],\"mem_max\":[%s]", \
                (si > 1 ? "," : ""), nm, series(nm, "cpu"), series(nm, "cpu_max"), series(nm, "mem"), series(nm, "mem_max")
            for (ki = 1; ki <= NK[nm]; ki++) {
                k = KN[nm, ki]
                printf ",\"%s\":[%s],\"%s_max\":[%s]", k, series(nm, k), k, series(nm, k "_max")
            }
            printf "}"
        }
        printf "},\n"
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
if [ ! -f "$q" ] || [ $(( now - $(mtime_of "$q") )) -ge 3300 ] || grep -q '^"t":\[\],$' "$q"; then
    rollup quarter $(( KEEP_DAYS * 86400 )) 3600
fi
