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
# hyrule-castle/scripts/fb2k-backup.sh for what protects them. The page build
# writes only under the checkout's agitha/ui/node_modules and agitha/ui/dist,
# and installs under /usr/local/lib/agitha.
set -euo pipefail

# One repo, two machines, two deploy scripts, and the paths differ by one
# directory. Run this on navi and it installs a Wine and Xvfb stack on the box
# that serves the flat's DNS, where the units fail and restart on a loop.
# That happened on 2026-09-22. Check first.
EXPECT_HOST=hyrule-castle
if [ "$(hostname)" != "$EXPECT_HOST" ]; then
    echo "refusing: this deploy is for $EXPECT_HOST, but this is $(hostname)"
    echo "navi's deploy is ./scripts/deploy.sh - this one is ./hyrule-castle/scripts/deploy.sh"
    exit 1
fi

# Pinned so a new pnpm release cannot change what a deploy builds. Bump it on
# purpose, with the lockfile.
PNPM=pnpm@10.34.6

REPO=$(cd "$(dirname "$0")/../.." && pwd)
USER_NAME=${SUDO_USER:-enrique-ramirez}
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "==> packages"
apt-get update
apt-get install -y --no-install-recommends python3-pil python3-mutagen libchromaprint-tools \
    libarchive-tools nodejs npm

# Wipe first so a module deleted from the package doesn't linger as a stale
# .py file that nothing in git references anymore.
echo "==> engine"
rm -rf /usr/local/lib/musiclib
mkdir -p /usr/local/lib/musiclib
cp -a "$REPO/hyrule-castle/music/musiclib" /usr/local/lib/musiclib/
find /usr/local/lib/musiclib -depth -name __pycache__ -exec rm -rf {} +

# The build runs as the checkout's owner so node_modules and dist do not turn
# root-owned.
echo "==> agitha page"
UI_SRC="$REPO/hyrule-castle/music/agitha/ui"
(cd "$UI_SRC" &&
    sudo -u "$USER_NAME" -H npx --yes "$PNPM" install --frozen-lockfile &&
    sudo -u "$USER_NAME" -H npx --yes "$PNPM" build)
mkdir -p /usr/local/lib/agitha
rm -rf /usr/local/lib/agitha/ui.new
cp -a "$UI_SRC/dist" /usr/local/lib/agitha/ui.new
rm -rf /usr/local/lib/agitha/ui
mv /usr/local/lib/agitha/ui.new /usr/local/lib/agitha/ui

# Wiped first, as the engine is.
echo "==> agitha server"
rm -rf /usr/local/lib/agitha/agitha
mkdir /usr/local/lib/agitha/agitha
for f in "$REPO"/hyrule-castle/music/agitha/*; do
    [ "$(basename "$f")" = ui ] || cp -a "$f" /usr/local/lib/agitha/agitha/
done
find /usr/local/lib/agitha -depth -name __pycache__ -exec rm -rf {} +

echo "==> scripts"
install -m 700 "$REPO/hyrule-castle/scripts/fb2k-backup.sh" /usr/local/bin/fb2k-backup.sh
install -m 755 "$REPO/hyrule-castle/scripts/musiclib" /usr/local/bin/musiclib

# A sudoers file with a syntax error breaks sudo for everything, and this box
# has no root SSH login to fix it with. So: validate it, write it under a
# dotted name (which sudo ignores), and rename it into place only if it passes.
echo "==> sudoers"
for s in "$REPO"/hyrule-castle/sudoers/*; do
    n=$(basename "$s")
    if ! cmp -s "$s" "/etc/sudoers.d/$n"; then
        install -m 440 -o root -g root "$s" "/etc/sudoers.d/$n.new"
        if visudo -cqf "/etc/sudoers.d/$n.new"; then
            mv "/etc/sudoers.d/$n.new" "/etc/sudoers.d/$n"
            echo "    updated $n"
        else
            rm -f "/etc/sudoers.d/$n.new"
            echo "    $n FAILED visudo, not installed"; exit 1
        fi
    fi
done

echo "==> directories"
mkdir -p /srv/fb2k /srv/backup
chown "$USER_NAME": /srv/fb2k
chmod 700 /srv/backup

# foo_jean's tag-write tests write to copies of fixture files in here, never to
# /srv/music. 'one' and 'two' get registered as library folders, and 'loose'
# deliberately does not. The files come from foo_jean's test-fixtures script;
# this only makes the folders, so they exist before anyone registers them.
# F:\foo_jean-test under Wine, next to the install, where that script looks.
for d in one two loose; do
    sudo -u "$USER_NAME" mkdir -p "/srv/fb2k/foo_jean-test/$d"
done

# The library index stores file-relative:// paths, so Musica must sit beside the
# install directory or 30,442 tracks come up dead. See docs/hyrule-castle.md.
if [ ! -e /srv/fb2k/Musica ]; then
    sudo -u "$USER_NAME" ln -s /srv/music/library /srv/fb2k/Musica
    echo "    created Musica symlink"
fi

# Wine puts the wineserver socket in /run/user/<uid> when that exists and in
# /tmp otherwise. Without linger, /run/user/<uid> exists only while someone is
# logged in, so the player's ExecStop could look somewhere other than where the
# running server put its socket. It then starts a second Wine session, and the
# stop hangs until TimeoutStopSec. Linger keeps the directory around from boot
# to shutdown. See "Stopping it correctly" in docs/hyrule-castle.md.
echo "==> linger"
loginctl enable-linger "$USER_NAME"

echo "==> systemd units"
changed=0
display=0
for u in "$REPO"/hyrule-castle/systemd/*; do
    n=$(basename "$u")
    if ! cmp -s "$u" "/etc/systemd/system/$n"; then
        install -m 644 "$u" "/etc/systemd/system/$n"; changed=1
        echo "    updated $n"
        case "$n" in
            xvfb.service|openbox.service|foobar2000.service) display=1 ;;
        esac
    fi
done

if [ "$changed" = 1 ]; then
    systemctl daemon-reload
    systemctl enable xvfb.service openbox.service foobar2000.service fb2k-backup.timer >/dev/null
    systemctl start fb2k-backup.timer
fi

if [ "$display" = 1 ]; then
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
    echo "    display stack unchanged, not restarted"
fi

echo "==> agitha"
systemctl enable agitha.service >/dev/null
systemctl restart agitha.service

echo "==> state"
for s in xvfb openbox foobar2000 agitha; do
    printf "    %-12s %s\n" "$s" "$(systemctl is-active $s.service)"
done
echo "==> done"
