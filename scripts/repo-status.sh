#!/bin/bash
# Writes a small JSON saying whether the checkout matches origin.
#
# Read-only on purpose. There is no deploy button and there shouldn't be: an
# HTTP endpoint that runs code as root on the box serving the flat's DNS,
# reachable by anything on the LAN including the washing machine, is not a
# trade worth making to save typing one SSH command.
#
# This just tells you a deploy is pending, which is the useful half.
set -u
REPO=/srv/navi
OUT=/srv/data/www/status.json
mkdir -p "$(dirname "$OUT")"

# Run git as the repo's owner, never as root. Root leaves root-owned objects in
# .git and the next `git pull` as enrique fails with a permissions error that
# looks like nothing to do with the cause.
OWNER=$(stat -c %U "$REPO")
as_owner() { runuser -u "$OWNER" -- "$@"; }

fetch_ok=true
as_owner git -C "$REPO" fetch -q origin 2>/dev/null || fetch_ok=false

commit=$(as_owner  git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)
subject=$(as_owner git -C "$REPO" log -1 --format=%s 2>/dev/null | tr -d '"\\' | cut -c1-70)
behind=$(as_owner  git -C "$REPO" rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
dirty=$(as_owner   git -C "$REPO" status --porcelain 2>/dev/null | wc -l)

cat > "$OUT" <<JSON
{"commit":"$commit","subject":"$subject","behind":${behind:-0},"dirty":${dirty:-0},"fetch_ok":$fetch_ok,"checked":"$(date -Is)"}
JSON
chmod 644 "$OUT"
