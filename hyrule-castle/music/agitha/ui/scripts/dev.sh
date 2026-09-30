#!/bin/bash
# `pnpm dev`: agitha's server and the page's dev server, both on this machine.
#
# The server runs from the checkout against scratch folders under the repo's
# _tmp/agitha-dev (gitignored), so a drop, an approve or a discard here never
# touches hyrule-castle. The library there starts empty; copy albums into
# _tmp/agitha-dev/library to try the duplicate check.
#
# musiclib runs from the checkout too, and still asks MusicBrainz and the
# Cover Art Archive over the internet. ACOUSTID_API_KEY is passed through
# when set.
#
# `pnpm dev:box` points the page at the real server on agitha.lan instead.
set -euo pipefail

ui=$(cd "$(dirname "$0")/.." && pwd)
music=$(cd "$ui/../.." && pwd)
repo=$(cd "$music/../.." && pwd)
scratch="$repo/_tmp/agitha-dev"
port="${AGITHA_PORT:-8882}"

python="$repo/_tmp/venv/bin/python"
if [ ! -x "$python" ]; then
    python=python3
fi
if ! "$python" -c "import mutagen, PIL" 2>/dev/null; then
    echo "dev.sh: $python has no mutagen or Pillow; musiclib needs both" >&2
    echo "        python3 -m venv $repo/_tmp/venv && $repo/_tmp/venv/bin/pip install mutagen Pillow" >&2
    exit 1
fi

mkdir -p "$scratch"/{inbox,jobs,library,extras,static}

# agitha takes musiclib as one executable, as /usr/local/bin/musiclib is on the box.
cat > "$scratch/musiclib" <<EOF
#!/bin/bash
export PYTHONPATH="$music"
exec "$python" -m musiclib "\$@"
EOF
chmod +x "$scratch/musiclib"

PYTHONPATH="$music" "$python" -m agitha \
    --host 127.0.0.1 --port "$port" \
    --inbox "$scratch/inbox" --jobs "$scratch/jobs" \
    --library "$scratch/library" --extras "$scratch/extras" \
    --static "$scratch/static" --musiclib "$scratch/musiclib" &
server=$!
trap 'kill $server 2>/dev/null' EXIT INT TERM

AGITHA_URL="http://127.0.0.1:$port" "$ui/node_modules/.bin/vite" "$@"
