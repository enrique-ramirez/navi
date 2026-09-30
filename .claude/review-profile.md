# Review profile

What the review agents need to know about this repository. They read this first and treat it as fact.

## Boundary

One repository, two machines, and each applies only its own half. Everything at the top level belongs to navi, the Raspberry Pi that serves the flat's DNS. `hyrule-castle/` belongs to the mini PC and is applied only on that box, by `hyrule-castle/scripts/deploy.sh`. Nothing at the top level may depend on `hyrule-castle/`, and nothing under `hyrule-castle/` may be installed on navi.

Both deploy scripts check `hostname` and refuse to run on the wrong machine, because running the hyrule-castle deploy on navi once installed a Wine stack on the DNS server (`docs/gotchas.md`, *One repo, two machines*). **A new deploy script without that guard, or a change that weakens one, is a finding.** A new machine gets the guard before it gets a deploy script.

Two further rules, enforced by `.gitignore` and by the deploy scripts rather than by a linter:

- **The repo is config, never state.** Runtime data lives in `/srv/data` on navi and in `/srv/fb2k`, `/srv/music` and the Wine prefix on hyrule-castle. `hyrule-castle/scripts/deploy.sh` never touches those. Flag anything that writes to them from a deploy, or commits a database, a backup or a tarball.
- **Secrets are in `.env` only.** `.env.example` lists every value with none filled in.

Deploys are run by a person on purpose (`README.md`). Flag anything that makes a push reconcile onto a box unattended.

## Excluded paths

- `.env`, `*.env` (secrets; `.env.example` is tracked and reviewed)
- `*.db`, `*.db-shm`, `*.db-wal`, `*.tar.gz`, `data/`, `backups/`
- `*.local.md`, `*.local.txt`, `*.local.bak`
- `_todo/`, `_done/`, `_tmp/` (gitignored scratch; `spec-planner` owns the first two)
- `.claude/` apart from `review-profile.md`, `register.local.txt` and `style-exempt.txt` (kit-managed, refreshed by `sync-kit.sh`)

## Functional directives

None in use today. If one appears it will be `# shellcheck disable=`, and it is never deleted or weakened.

## Doc comments

Shell scripts carry a header comment saying what the script does, where it runs and how it is invoked. That header is judged like any other comment, but the *where it runs* and *what it never touches* lines are load-bearing and stay: they are the same guarantees the boundary above relies on. Nothing lints for comments, so there is no floor beyond that.

## Documentation map

| file | audience | its job |
|---|---|---|
| `README.md` | whoever opens the repo | what navi is, what runs on it, how to change something, and the index of `docs/` |
| `hyrule-castle/README.md` | whoever applies config on the mini PC | what is in that directory and how it is applied. The machine itself is in `docs/hyrule-castle.md` |
| `docs/*.md` | the owner, months later, usually mid-outage | one subject per file; `README.md` holds the index with one line on each |

`docs/runbook.md` is read during an outage, so it leads with commands. `docs/decisions.md` holds the why, `docs/gotchas.md` the things that cost hours, and `docs/future-plans.md` what has not been built. There is no `CLAUDE.md`, `CONTRIBUTING.md` or `ARCHITECTURE.md`.

## Where an external fact belongs

The `docs/` file for that machine or subject: `docs/er605.md` for the router, `docs/navi.md` and `docs/hyrule-castle.md` for the two boxes, `docs/network.md` for addressing and names, `docs/hosting.md` for anything outside the flat. Something that cost hours to find goes in `docs/gotchas.md` as well.

## Commands

| | |
|---|---|
| syntax of one script | `bash -n scripts/wan-check.sh` |
| lint one script, where installed | `shellcheck scripts/wan-check.sh` (not installed on the MacBook today) |
| one engine module | `cd hyrule-castle/music && ../../_tmp/venv/bin/python -m unittest tests.test_<name>` |
| the whole engine suite | `cd hyrule-castle/music && ../../_tmp/venv/bin/python -m unittest` (about two and a half minutes, run alone: its server cases poll with deadlines and can flake under load) |
| page lint (Biome) | `cd hyrule-castle/music/agitha/ui && pnpm lint` |
| page typecheck | `pnpm typecheck` (`tsc -b`), same folder |
| one page test file | `pnpm exec vitest run src/features/drop/DropArea.test.tsx`, same folder |
| every page test | `pnpm exec vitest run`, same folder (a few seconds) |
| page build | `pnpm build`, same folder |

The engine under `hyrule-castle/music/` has a test suite. The venv is `_tmp/venv`, gitignored and made by the owner: `python3 -m venv _tmp/venv && _tmp/venv/bin/pip install mutagen pillow`. The shell scripts have no tests. `scripts/thermal-test.sh` is a hardware load test for navi, not a test of the code, and must not be run from a review.

The page (`hyrule-castle/music/agitha/ui/`) is React on Vite, tested with Vitest and Testing Library. Its conventions:

- A test sits beside its component as `Thing.test.tsx`.
- Components render through `src/test/render.tsx`, which wraps the Query client, the router and the catalogue.
- The network is faked at `fetch` with a per-test handler table in `src/test/fakeFetch.ts`.
- Queries go by role and name. Interaction goes through `user-event`.

## What cannot be verified here

Nearly all of the box's side of it. Every script and unit runs on navi (Raspberry Pi, Raspberry Pi OS) or on hyrule-castle (x86, Debian 13), under systemd and Docker, against real hardware, the router and two ISP lines. A change is reviewed, not tested, unless somebody runs it on the box. The deploy scripts refuse to run on the MacBook by design.

The engine and page tests pass on the Mac and still leave these unchecked:

- The real drop and folder walk in a browser.
- RAR extraction on Debian.
- Playback in a real browser.
- The look at each width and theme, and the favicon.
- Caddy and Pi-hole on navi.
- The deploy, and the page build on the box.
- Whether foobar2000 under Wine sees a new folder while it is running.

## Voice

- Documentation and comments: `enrique`, falling back to `house` where that persona file is not in the checkout.
- Text posted under a person's name: `enrique`.

## Product decisions

The owner decides. A change to what is exposed on the network, to what a deploy installs or enables, to monitoring thresholds or alert routing, or to where data lives is a decision rather than an implementation detail. An agent that finds one in a diff with no sign the owner was asked reports it as a finding and does not implement it.
