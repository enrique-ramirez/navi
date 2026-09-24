# hyrule-castle

Config for the mini PC. The machine itself is described in
[../docs/hyrule-castle.md](../docs/hyrule-castle.md); this directory is only what
gets applied to it.

## What's here

```
systemd/   xvfb, openbox, foobar2000, and the profile backup timer
scripts/   deploy.sh, fb2k-backup.sh
sudoers/   passwordless systemctl stop/start/restart foobar2000, for foo_jean deploys
```

## Applying it

Same rule as navi, and for the same reason: a human runs the deploy.

The repo has to be checked out on hyrule-castle first - it is the same repo navi
uses, and the two machines each apply their own half:

```sh
# once, on hyrule-castle
sudo mkdir -p /srv/navi && sudo chown enrique-ramirez: /srv/navi
git clone git@github.com:enrique-ramirez/navi.git /srv/navi
```

```sh
# on your laptop
edit, commit, push

# on hyrule-castle
ssh enrique-ramirez@hyrule-castle.lan
cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
```

**Both deploy scripts check `hostname` and refuse to run on the wrong machine.**
That guard exists because this one was run on navi by mistake, which installed a
Wine and Xvfb stack on the flat's DNS server.

`deploy.sh` installs the units and the sudoers drop-in, which it checks with
`visudo` first. It creates `/srv/fb2k`, the `Musica` symlink, and the empty
`foo_jean-test/` tree if any of them are missing, and restarts the display stack **only when a unit actually changed**.
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
progress. What its deploy needs from this box is already here: the sudoers rule,
and `/srv/fb2k/foo_jean-test/`. Registering `one` and `two` in that tree as
library folders is a manual GUI step. See
[../docs/hyrule-castle.md](../docs/hyrule-castle.md). When it lands, `MUSIC_BACKEND` and `MUSIC_FOOJEAN` in navi's `.env`
move to `10.100.100.50:8881` and the Caddy vhosts follow.

Backups are local only, in `/srv/backup`. Same gap the top-level README notes for
navi: both copies are in the same flat.
