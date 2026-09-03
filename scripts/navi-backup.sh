#!/bin/bash
# Backs up only what git can't hold.
#
# Since the config moved into the repo, this shrank to the un-versionable bits:
# the secrets file, Kuma's database (monitor definitions and history), and a
# few facts that make a rebuild match rather than approximate.
#
# Deliberately NOT included:
#   gravity.db (12MB)   regenerable with `pihole -g`
#   pihole-FTL.db       query history, not worth carrying
#   docker images       re-pull
#   anything in /srv/navi   it's in git
#
# CONTAINS SECRETS: .env holds the Pi-hole password and all five push tokens.
# Tarball is mode 600. Any copy inherits that.
set -u
OUT=/srv/backup/navi-state-$(date +%Y%m%d-%H%M).tar.gz
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

sqlite3 /srv/data/pihole/etc-pihole/gravity.db \
  ".mode insert adlist" "select * from adlist" > "$TMP/adlist.sql" 2>/dev/null || true
dpkg --get-selections > "$TMP/dpkg-selections.txt"
rpi-eeprom-config    > "$TMP/eeprom-config.txt" 2>/dev/null || true
git -C /srv/navi rev-parse HEAD > "$TMP/repo-commit.txt" 2>/dev/null || true

tar czf "$OUT" \
  -C / srv/navi/.env srv/data/uptime-kuma/kuma.db \
  -C "$TMP" adlist.sql dpkg-selections.txt eeprom-config.txt repo-commit.txt 2>/dev/null

chmod 600 "$OUT"
ls -1t /srv/backup/navi-state-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "$(date -Is)  $(du -h "$OUT" | cut -f1)  $OUT"
