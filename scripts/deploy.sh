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
    systemctl enable --now wan-check.timer navi-backup.timer >/dev/null
fi

echo "==> state directories"
mkdir -p /srv/data/{pihole/etc-pihole,uptime-kuma,caddy} /srv/backup
chmod 700 /srv/backup

echo "==> compose stacks"
for s in pihole uptime-kuma caddy; do
    echo "    $s"
    ( cd "$REPO/stack/$s" && docker compose --env-file "$REPO/.env" up -d )
done

echo "==> done"
docker ps --format '    {{.Names}}  {{.Status}}'
