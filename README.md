# navi

The Raspberry Pi that runs the house network. It resolves DNS for every device in
the flat, blocks ads, watches both ISP lines, and gives the machines names worth
remembering.

It exists because a Telmex outage went unnoticed for two weeks. There are two ISP
lines and the router fails between them silently, so losing one produces no
symptom at all: the internet keeps working, you've just quietly stopped having a
spare. Nothing in the house could tell you that had happened. Now something can.

## What runs on it

| Service | Reachable at | Does |
|---|---|---|
| Pi-hole | `dns.lan` | DNS for the flat, ad blocking, local names |
| Uptime Kuma | `status.lan` | 13 monitors, alerts to ntfy on the phone |
| Caddy | port 80 | reverse proxy, so everything has a name instead of a port |
| `wan-check.timer` | every 5 min | the checks Kuma can't make itself |
| `host-status.timer` | every 28 sec | samples this box's own vitals for the page |
| `host-history.timer` | every 5 min | rolls those samples into 24h / 7d / 90d charts |
| landing page | `help.lan` | links, runbook and navi's vitals, also on the bare IP |

## Repo layout

```
stack/          docker compose per service, plus the Caddyfile
scripts/        wan-check, backup, deploy
systemd/        timers and units
www/            the help.lan landing page
hyrule-castle/  the mini PC's units and scripts, applied on that box
docs/           everything below
.env.example    every value you need; the real .env is gitignored
```

Everything at the top level belongs to navi. `hyrule-castle/` is the second
machine, deployed separately on that box - see
[hyrule-castle/README.md](hyrule-castle/README.md). The docs cover both.

## Changing something

The repo is the source of truth. `navi` has it checked out at `/srv/navi` and
pulls from it.

```sh
# on your laptop
edit, commit, push

# on navi
ssh enrique@navi.lan          # or 10.100.100.53 if DNS is down, which is
                              # exactly when you'll need to get in
cd /srv/navi && git pull && sudo ./scripts/deploy.sh
```

hyrule-castle has its own deploy on the same repo:

```sh
ssh enrique-ramirez@hyrule-castle.lan
cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
```

`deploy.sh` copies scripts and units into place, reloads systemd if they changed,
creates any missing state directories, and brings the compose stacks up. Running
it when nothing changed is safe and near-instant.

There's no auto-pull, and that's on purpose. Real GitOps reconciles continuously,
but a bad push reconciling itself onto the box that serves the flat's DNS at 3am
is worse than a config that's a few hours stale. A human runs the deploy.

## Config vs. state

Config lives here. State lives in `/srv/data` on navi and never enters the repo:
Pi-hole's databases, Kuma's history, Caddy's data directory, 90 days of vitals. That split means
`git clean` can't eat your query history, and the repo stays a few hundred KB
instead of 30 MB.

## Secrets

`/srv/navi/.env`, mode 600, gitignored. Real values are in 1Password. Copy
`.env.example` and fill it in. Nothing else in the repo should ever hold a
password or a token.

## Docs

| Doc | Covers |
|---|---|
| [network.md](docs/network.md) | The house. Two ISPs, the router, addressing, naming |
| [wifi.md](docs/wifi.md) | The Decos, roaming, and what's still unsolved |
| [er605.md](docs/er605.md) | The router, written out so it can be rebuilt |
| [navi.md](docs/navi.md) | The box. Hardware, boot, services, updates |
| [hyrule-castle.md](docs/hyrule-castle.md) | The mini PC. Hardware, BIOS, network, what's left |
| [music-library.md](docs/music-library.md) | The rules every album follows: layout, names, tags, images |
| [https.md](docs/https.md) | Certificates, why they exist, installing the root |
| [monitoring.md](docs/monitoring.md) | What's watched, and why each check exists |
| [runbook.md](docs/runbook.md) | When something breaks |
| [decisions.md](docs/decisions.md) | Why it's built this way |
| [gotchas.md](docs/gotchas.md) | The things that cost hours |
| [future-plans.md](docs/future-plans.md) | What's next: the music migration, the staged storage buy, the NAS |
| [tailscale.md](docs/tailscale.md) | Remote access, the procedure, not yet run |
| [hosting.md](docs/hosting.md) | Domains, email, the public sites, the offsite copy |
