#!/bin/bash
# Apply whatever is currently checked out. Run on navi after a git pull:
#
#     cd /srv/navi && git pull && sudo ./scripts/deploy.sh
#
# Deliberately not automatic. A push that breaks DNS should not reconcile
# itself onto the box at 3am while nobody is watching.
set -euo pipefail

REPO=/srv/navi
[ -f "$REPO/.env" ] || { echo "missing $REPO/.env - copy .env.example and fill it in"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "==> scripts"
install -m 700 "$REPO/scripts/wan-check.sh"   /usr/local/bin/wan-check.sh
install -m 700 "$REPO/scripts/navi-backup.sh" /usr/local/bin/navi-backup.sh
install -m 700 "$REPO/scripts/repo-status.sh"  /usr/local/bin/repo-status.sh
install -m 700 "$REPO/scripts/host-status.sh"  /usr/local/bin/host-status.sh
install -m 755 "$REPO/scripts/thermal-test.sh" /usr/local/bin/thermal-test.sh
install -m 755 "$REPO/scripts/tv-launcher.py"  /usr/local/bin/tv-launcher.py

# Samsung's remote API is a WebSocket, so tv-launcher.py needs a client. Checked
# rather than installed: nothing else in this deploy touches apt, and a script
# that silently pulls packages onto the box that serves the flat's DNS is not
# the kind of surprise this repo is meant to contain.
echo "==> tv-launcher prerequisites"
if ! python3 -c 'import websocket' 2>/dev/null; then
    echo "    !! python3-websocket missing. Install it, then re-run:"
    echo "       sudo apt install python3-websocket"
    exit 1
fi
# No shell, no home. It exists to own the pairing token and hold a socket open.
if ! id navi-tv >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin navi-tv
    echo "    created user navi-tv"
fi

# .env is gitignored, so `git pull` can add a key to .env.example and NEVER add
# it to the real file. Any service that needs a new key therefore deploys
# "successfully" onto a box where it cannot start. Check the keys this one
# needs, by name, before installing a unit that would crash-loop without them.
# Worth repeating for the next service that grows a config key.
for k in TV_HOST TV_URL; do
    grep -qE "^${k}=." "$REPO/.env" || {
        echo "    !! $k is missing from $REPO/.env"
        echo "       .env is gitignored, so the pull could not add it for you."
        echo "       Copy the TV_* block out of .env.example, then re-run."
        exit 1
    }
done
# Created here rather than with the other state directories below, because
# ProtectSystem=strict + ReadWritePaths means the unit refuses to start if this
# path doesn't already exist, and the unit is started before that block runs.
mkdir -p /srv/data/tv
chown navi-tv:navi-tv /srv/data/tv
chmod 700 /srv/data/tv

echo "==> systemd units"
changed=0
for u in "$REPO"/systemd/*; do
    n=$(basename "$u")
    if ! cmp -s "$u" "/etc/systemd/system/$n"; then
        install -m 644 "$u" "/etc/systemd/system/$n"; changed=1
        echo "    updated $n"
    fi
done
if [ "$changed" = 1 ]; then
    systemctl daemon-reload
    systemctl enable --now wan-check.timer navi-backup.timer repo-status.timer host-status.timer >/dev/null
    systemctl enable --now tv-launcher.service >/dev/null
fi

# The timers re-read their script every time they fire, so installing the file
# is enough for them. tv-launcher is a long-running process that read its code
# and its .env once at startup, so it keeps serving the OLD version until told
# otherwise. Same trap as the Caddyfile bind mount further down.
systemctl restart tv-launcher.service
# And then actually look. A deploy that prints "done" while a service it just
# started is dead is worse than one that fails, because you go and press the
# button and blame the TV.
sleep 1
if ! systemctl is-active --quiet tv-launcher.service; then
    echo "    !! tv-launcher is not running:"
    journalctl -u tv-launcher.service -n 5 --no-pager | sed 's/^/       /'
fi


echo "==> state directories"
mkdir -p /srv/data/{pihole/etc-pihole,uptime-kuma,caddy,www} /srv/backup
chmod 700 /srv/backup

echo "==> compose stacks"
for s in pihole uptime-kuma caddy; do
    echo "    $s"
    ( cd "$REPO/stack/$s" && docker compose --env-file "$REPO/.env" up -d )
done

# Caddy reads its config once at startup and the Caddyfile is a bind mount, so
# `compose up -d` sees no change to the image or compose file and leaves the
# container running the OLD config. The deploy reports success and applies
# nothing. Restart it explicitly.
#
# Validate first, inside the running container so it sees the new file and the
# compose environment. If the new config is broken, leave the working one
# running rather than restarting into a failure.
echo "==> caddy config"
if docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
    docker restart caddy >/dev/null
    echo "    valid, restarted"
else
    echo "    !! INVALID - not restarting, previous config still serving:"
    docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -i error | head -3 | sed 's/^/       /'
fi

echo "==> done"
docker ps --format '    {{.Names}}  {{.Status}}'
