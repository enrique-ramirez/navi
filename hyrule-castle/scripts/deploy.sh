#!/bin/bash
# Apply whatever is currently checked out, on hyrule-castle:
#
#     cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
#
# Deliberately not automatic, for the reason the top-level README gives: a push
# that breaks something should not reconcile itself onto the box unattended.
#
# This manages CONFIG only. It never touches /srv/fb2k/foobar2000 (binaries and
# profile), the wine prefix, or /srv/music. Those are state; see
# hyrule-castle/scripts/fb2k-backup.sh for what protects them.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
USER_NAME=${SUDO_USER:-enrique-ramirez}
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "==> scripts"
install -m 700 "$REPO/hyrule-castle/scripts/fb2k-backup.sh" /usr/local/bin/fb2k-backup.sh

echo "==> directories"
mkdir -p /srv/fb2k /srv/backup
chown "$USER_NAME": /srv/fb2k
chmod 700 /srv/backup

# The library index stores file-relative:// paths, so Musica must sit beside the
# install directory or 30,442 tracks come up dead. See docs/hyrule-castle.md.
if [ ! -e /srv/fb2k/Musica ]; then
    sudo -u "$USER_NAME" ln -s /srv/music/library /srv/fb2k/Musica
    echo "    created Musica symlink"
fi

echo "==> systemd units"
changed=0
for u in "$REPO"/hyrule-castle/systemd/*; do
    n=$(basename "$u")
    if ! cmp -s "$u" "/etc/systemd/system/$n"; then
        install -m 644 "$u" "/etc/systemd/system/$n"; changed=1
        echo "    updated $n"
    fi
done

if [ "$changed" = 1 ]; then
    systemctl daemon-reload
    systemctl enable xvfb.service openbox.service foobar2000.service fb2k-backup.timer >/dev/null
    systemctl start fb2k-backup.timer

    # Order matters and is not obvious. foobar2000 is an X client of Xvfb, so
    # restarting Xvfb first kills it abnormally however the dependency graph
    # reads - and an abnormal exit makes foobar2000 open a modal "terminated
    # abnormally" dialog on next start, which on a headless box is a hang that
    # reports itself as running. Stop the client cleanly, then the server.
    echo "==> restarting display stack in order"
    systemctl stop foobar2000.service || true
    systemctl restart xvfb.service
    systemctl restart openbox.service
    systemctl start foobar2000.service
else
    echo "    no unit changes, nothing restarted"
fi

echo "==> state"
for s in xvfb openbox foobar2000; do
    printf "    %-12s %s\n" "$s" "$(systemctl is-active $s.service)"
done
echo "==> done"
