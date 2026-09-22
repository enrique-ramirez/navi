# hyrule-castle

Config for the mini PC. The machine itself is described in
[../docs/hyrule-castle.md](../docs/hyrule-castle.md); this directory is only what
gets applied to it.

## What's here

```
systemd/   xvfb, openbox, foobar2000, and the profile backup timer
scripts/   deploy.sh, fb2k-backup.sh
```

## Applying it

Same rule as navi, and for the same reason: a human runs the deploy.

```sh
# on your laptop
edit, commit, push

# on hyrule-castle
ssh enrique-ramirez@10.100.100.50      # or hyrule-castle.lan
cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
```

`deploy.sh` installs the units, creates `/srv/fb2k` and the `Musica` symlink if
missing, and restarts the display stack **only when a unit actually changed**.
When it does restart, it stops foobar2000 before touching Xvfb - the order is
load-bearing and the script says why.

## Config vs. state, and why almost nothing is in git

The same split the top-level README makes for navi. Config lives here; state
lives in `/srv` and never enters the repo.

| Not in git | Why |
|---|---|
| `/srv/fb2k/foobar2000/` | 25 MB of binaries, re-downloadable |
| `profile/config.sqlite` | **holds the Last.fm session** |
| `profile/metadb.sqlite` | 92 MB, rewritten constantly |
| `profile/library-v2.0` | regenerable by rescanning |
| `~/fb2k-wine/` | the Wine prefix, disposable by design |
| `/srv/music/` | the library |

So this directory is a few KB of units and shell, and holds no secret.

**That split leaves a hole, and `fb2k-backup.sh` fills it.** `metadb.sqlite` is
where every play count, rating and date-added lives, and it is in neither git nor
anything else. The backup runs daily, keeps fifteen, and is mode 600 because
`config.sqlite` carries a credential.

It copies the two databases through SQLite's online backup API rather than `cp`.
foobar2000 holds them open and writes while running; a plain copy of a live
database can be internally inconsistent, and that failure surfaces later as
missing play counts rather than as an error.

## Not here yet

`foo_jean` is deliberately not installed - the migration off beefweb is still in
progress. When it lands, `MUSIC_BACKEND` and `MUSIC_FOOJEAN` in navi's `.env`
move to `10.100.100.50:8881` and the Caddy vhosts follow.

Backups are local only, in `/srv/backup`. Same gap the top-level README notes for
navi: both copies are in the same flat.
