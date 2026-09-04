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
install -m 755 "$REPO/scripts/thermal-test.sh" /usr/local/bin/thermal-test.sh

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
    systemctl enable --now wan-check.timer navi-backup.timer repo-status.timer >/dev/null
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
