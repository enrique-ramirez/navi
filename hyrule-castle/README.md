# hyrule-castle

Config for the mini PC. The machine itself is described in [../docs/hyrule-castle.md](../docs/hyrule-castle.md); this directory is only what gets applied to it.

## What's here

```
systemd/      xvfb, openbox, foobar2000, agitha, the profile backup timer, and the vitals page's units
scripts/      deploy.sh, fb2k-backup.sh
sudoers/      passwordless systemctl stop/start/restart foobar2000, for foo_jean deploys, and the
              two restart commands the vitals page may run
vitals.conf   this box's file for the vitals kit in ../vitals/, installed as /etc/vitals.conf
music/        musiclib, the engine that identifies, tags and names releases against docs/music-library.md
              agitha/, the import page in front of it: a Python server and a React page (agitha/ui/)
```

## Applying it

Same rule as navi, and for the same reason: a human runs the deploy.

The repo has to be checked out on hyrule-castle first - it is the same repo navi uses, and the two machines each apply their own half:

```sh
# once, on hyrule-castle
sudo apt install git
ssh-keygen -t ed25519 -f ~/.ssh/navi_deploy -N "" -C "hyrule-castle deploy key"
cat ~/.ssh/navi_deploy.pub    # GitHub -> Settings -> Deploy keys, read-only
# plus the same `Host github.com` block in ~/.ssh/config as navi,
# see docs/runbook.md, "Rebuilding from nothing"
sudo mkdir -p /srv/navi && sudo chown enrique-ramirez: /srv/navi
git clone git@github.com:enrique-ramirez/navi.git /srv/navi
```

The repo is private, and hyrule-castle has its own deploy key rather than navi's. GitHub refuses to attach one key to two repos, but one repo can take several keys. Each machine's key is regenerated rather than backed up, for the reason the runbook gives.

**Until the first `deploy.sh` run, nothing in this directory is live.** The first units were copied over by hand, which left `fb2k-backup.timer` never installed and play counts unprotected. `deploy.sh` is what installs it.

```sh
# on your laptop
edit, commit, push

# on hyrule-castle
ssh enrique-ramirez@hyrule-castle.lan
cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
```

**Both deploy scripts check `hostname` and refuse to run on the wrong machine.** That guard exists because this one was run on navi by mistake, which installed a Wine and Xvfb stack on the flat's DNS server.

`deploy.sh` installs the units and the sudoers drop-ins, which it checks with `visudo` first. It creates `/srv/fb2k`, the `Musica` symlink, and the empty `foo_jean-test/` tree if any of them are missing, and restarts the display stack **only when one of its own three units changed**. When it does restart, it stops foobar2000 before touching Xvfb - the order is load-bearing and the script says why.

For agitha it also installs Debian's `nodejs`, `npm` and `libarchive-tools`, builds the page with a pinned pnpm run through `npx`, and copies the server, `musiclib` and the built page into `/usr/local/lib/agitha` and `/usr/local/lib/musiclib`. The page is installed only after a good build. `agitha.service` is enabled and restarted on every run.

For the vitals page it creates the `vitals` system user (no shell, no home), copies `../vitals/` to `/usr/local/lib/vitals` without its tests, and installs `vitals.conf` as `/etc/vitals.conf` after checking that it parses (a file that fails stops the deploy there and leaves the old install in place). It makes `/srv/data/{www,history,logs}`. It restarts `host-page.service` on every run and runs `host-history.sh` once, so the history files exist before the first timer fires. It writes no samples. [../docs/hyrule-castle.md](../docs/hyrule-castle.md) has what the page does.

## Config vs. state, and why almost nothing is in git

The same split the top-level README makes for navi. Config lives here; state lives in `/srv` and never enters the repo.

| Not in git | Why |
|---|---|
| `/srv/fb2k/foobar2000/` | 25 MB of binaries, re-downloadable |
| `profile/config.sqlite` | **holds the Last.fm session** |
| `profile/metadb.sqlite` | 92 MB, rewritten constantly |
| `profile/library-v2.0` | regenerable by rescanning |
| `~/fb2k-wine/` | the Wine prefix, disposable by design |
| `/srv/music/` | the library |
| `/srv/data/` | state: 90 days of vitals samples, their rollups and the sampler's cursors |

So this directory is units, shell, the engine and the page source, and holds no secret.

**That split leaves a hole, and `fb2k-backup.sh` fills it.** `metadb.sqlite` is where every play count, rating and date-added lives, and it is in neither git nor anything else. The backup runs daily, keeps fifteen, and is mode 600 because `config.sqlite` carries a credential.

It copies the two databases through SQLite's online backup API rather than `cp`. foobar2000 holds them open and writes while running; a plain copy of a live database can be internally inconsistent, and that failure surfaces later as missing play counts rather than as an error.

## Not here yet

`foo_jean` is deliberately not installed - the migration off beefweb is still in progress. What its deploy needs from this box is already here: the sudoers rule, and `/srv/fb2k/foo_jean-test/`. Registering `one` and `two` in that tree as library folders is a manual GUI step. See [../docs/hyrule-castle.md](../docs/hyrule-castle.md). When it lands, `MUSIC_BACKEND` in navi's `.env` moves to `10.100.100.50:8881`. The Caddyfile already expects that.

Backups are local only, in `/srv/backup`. Same gap the top-level README notes for navi: both copies are in the same flat.
