#!/bin/bash
# Ten minute all-core soak, logging temperature, throttle flags and clock.
# Re-run after any hardware change (case, paste, PSU, adding a disk).
#
# Run it under systemd so it cannot outlive its welcome if something wedges:
#
#   sudo systemd-run --unit=thermal-test --collect --property=RuntimeMaxSec=660 \
#        /usr/local/bin/thermal-test.sh
#   sudo systemd-run --on-active=720 --unit=thermal-killer --collect \
#        /bin/bash -c 'pkill -9 -x stress-ng; systemctl stop thermal-test.service'
#
# That gives three independent stops (stress-ng's own timeout, RuntimeMaxSec,
# the killer timer) on top of the hardware watchdog, which resets the board if
# the kernel hangs for 60s. Results land in /tmp/thermal2.log, so they survive
# losing the SSH session.
LOG=/tmp/thermal2.log
echo "start $(date +%H:%M:%S) idle=$(vcgencmd measure_temp) case=ASSEMBLED" > "$LOG"
stress-ng --cpu 4 --timeout 600s >/dev/null 2>&1 &
SP=$!
while kill -0 $SP 2>/dev/null; do
    echo "$(date +%H:%M:%S) $(vcgencmd measure_temp) $(vcgencmd get_throttled) freq=$(vcgencmd measure_clock arm | cut -d= -f2)" >> "$LOG"
    sleep 15
done
echo "end $(date +%H:%M:%S) $(vcgencmd measure_temp) $(vcgencmd get_throttled)" >> "$LOG"
