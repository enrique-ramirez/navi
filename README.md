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
| Uptime Kuma | `status.lan` | 11 monitors, alerts to ntfy on the phone |
| Caddy | port 80 | reverse proxy, so everything has a name instead of a port |
| `wan-check.timer` | every 5 min | the checks Kuma can't make itself |
| landing page | `help.lan` | links and the runbook, also on the bare IP |

## Repo layout

```
stack/          docker compose per service, plus the Caddyfile
scripts/        wan-check, backup, deploy
systemd/        timers and units
www/            the help.lan landing page
docs/           everything below
.env.example    every value you need; the real .env is gitignored
```

## Changing something

The repo is the source of truth. `navi` has it checked out at `/srv/navi` and
pulls from it.

```sh
# on your laptop
edit, commit, push

# on navi
cd /srv/navi && git pull && sudo ./scripts/deploy.sh
```

`deploy.sh` copies scripts and units into place, reloads systemd if they changed,
creates any missing state directories, and brings the compose stacks up. Running
it when nothing changed is safe and near-instant.

There's no auto-pull, and that's on purpose. Real GitOps reconciles continuously,
but a bad push reconciling itself onto the box that serves the flat's DNS at 3am
is worse than a config that's a few hours stale. A human runs the deploy.

## Config vs. state

Config lives here. State lives in `/srv/data` on navi and never enters the repo:
Pi-hole's databases, Kuma's history, Caddy's data directory. That split means
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
| [navi.md](docs/navi.md) | The box. Hardware, boot, services, updates |
| [monitoring.md](docs/monitoring.md) | What's watched, and why each check exists |
| [runbook.md](docs/runbook.md) | When something breaks |
| [decisions.md](docs/decisions.md) | Why it's built this way |
| [gotchas.md](docs/gotchas.md) | The things that cost hours |
| [future-plans.md](docs/future-plans.md) | What's next, including the mini PC |
