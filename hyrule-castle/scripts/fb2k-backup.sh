#!/bin/bash
# Backs up only what git can't hold.
#
# The repo carries this box's config. Everything foobar2000 accumulates is state
# and lives outside it, so this covers the un-versionable bits:
#
#   metadb.sqlite     every play count, rating and date-added. Irreplaceable.
#                     foobar2000's own playCount column is empty here; the real
#                     data lives in the GUID-named metadb_index_* tables that
#                     foo_enhanced_playcount owns. Same file either way.
#   config.sqlite     every preference, including the Last.fm session
#   playlists-v2.0    playlists
#   configuration/    per-component settings
#
# Deliberately NOT included:
#   library-v2.0      the media library index. Regenerable by rescanning, and
#                     dateAdded lives in metadb.sqlite rather than here, so a
#                     rebuild costs time and loses nothing.
#   foobar2000.exe    and the rest of the install. Re-downloadable; the version
#                     is recorded below so a rebuild can match it.
#   components        same reasoning. The list is recorded.
#   the wine prefix   disposable by design. See docs/hyrule-castle.md.
#   /srv/music        the library itself. Far too large, and backed up by the
#                     offsite plan in docs/future-plans.md.
#
# CONTAINS SECRETS: config.sqlite holds the Last.fm session. Tarball is mode 600
# and any copy inherits that.
#
# The two SQLite files are copied with sqlite3's online backup API, not `cp`.
# foobar2000 holds them open and writes to them while running; a plain copy of a
# live database can be internally inconsistent, and the damage shows up later as
# missing play counts rather than as an error.
set -u

PROFILE=/srv/fb2k/foobar2000/profile
OUT=/srv/backup/fb2k-state-$(date +%Y%m%d-%H%M).tar.gz
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

[ -d "$PROFILE" ] || { echo "no profile at $PROFILE"; exit 1; }
mkdir -p /srv/backup

for db in metadb config; do
    python3 - "$PROFILE/$db.sqlite" "$TMP/$db.sqlite" <<'PY' || { echo "backup of $db.sqlite FAILED"; exit 1; }
import sqlite3, sys
src = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.execute("pragma integrity_check").fetchone()[0] == "ok" or sys.exit(1)
dst.close(); src.close()
PY
done

cp -a "$PROFILE/playlists-v2.0" "$PROFILE/configuration" "$TMP/" 2>/dev/null || true
for f in theme.fth config.fb2k-dsp; do
    [ -e "$PROFILE/$f" ] && cp -a "$PROFILE/$f" "$TMP/"
done
[ -d "$PROFILE/dsp-presets" ] && cp -a "$PROFILE/dsp-presets" "$TMP/"

# A rebuild should be able to match rather than approximate.
cat "$PROFILE/version.txt"                      > "$TMP/fb2k-version.txt" 2>/dev/null || true
ls  "$PROFILE/user-components-x64"              > "$TMP/components.txt"   2>/dev/null || true
dpkg --get-selections                           > "$TMP/dpkg-selections.txt"
wine --version                                  > "$TMP/wine-version.txt" 2>/dev/null || true
git -C "$(dirname "$0")/../.." rev-parse HEAD   > "$TMP/repo-commit.txt"  2>/dev/null || true

tar czf "$OUT" -C "$TMP" . 2>/dev/null
chmod 600 "$OUT"

ls -1t /srv/backup/fb2k-state-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "$(date -Is)  $(du -h "$OUT" | cut -f1)  $OUT"
