# Why it's built this way

Settled, with reasons, so they don't get relitigated.

## navi and ocarina stay separate machines

The mini PC will run media services. It doesn't also run DNS, for three reasons.

It's the machine that gets updated, restarted and actively developed against.
`foo_jean` is built and tested there, so crashes are expected. House DNS can't
live on a box with that duty cycle.

The monitor must not share a failure domain with what it monitors. If Kuma ran on
the media server, a failure there would take out both the service and the thing
that would have told you, which reproduces the exact silent-failure bug this box
was bought to fix.

And the Pi was already paid for. Consolidating recovers nothing.

## Pi-hole, not AdGuard Home

AdGuard is easier to run. Pi-hole has a bigger community, more knobs, and there's
nothing AdGuard does that Pi-hole can't reach with modest effort.

v6 was a rough release (it dropped lighttpd and PHP, broke every third-party
dashboard, and shipped a post-release fixes blog three days later) but that
transition is over and v5 is dead. We arrived after the pain.

## No secondary DNS

The tempting move is handing out `1.1.1.1` alongside Pi-hole so the flat degrades
gracefully. It's the wrong call: clients fall back to the public resolver whenever
navi is merely slow, so ads appear intermittently and unpredictably, and you can
never tell whether blocking is working.

Instead, Pi-hole is the only resolver, and monitor 8 watches it. `tatl` will
eventually provide real failover with two blocking resolvers, which is the
combination a public secondary can't give you.

## HaGeZi Multi NORMAL, one list, not Pro

Replaced StevenBlack's 78,609 domains with HaGeZi's 190,433.

One list rather than several. Pi-hole deduplicates, so a second list adds little
coverage but destroys attribution: when a site breaks you no longer know which
list did it, and removing one may not fix it. Stacking blocklists is the most
common cause of Pi-hole maintenance pain.

NORMAL rather than PRO because Pro blocks error and crash trackers, including
Firebase. On Android that's push notifications, remote config and auth, not just
crash reporting. The failure mode is notifications silently not arriving, which
nobody attributes to DNS for weeks. Escalating is a one-word change in `.env` if
you decide you want it.

HaGeZi blocks ad-serving hosts rather than corporate apexes. `criteo.com`
resolves, `static.criteo.net` doesn't. That's more surgical than StevenBlack's
approach and breaks fewer opt-out pages.

## SSD, not the SD card

Pi-hole and Kuma both write constantly. The SSD gives 339/227 MB/s against maybe
20 MB/s from the card, and doesn't wear out. The card stays as a complete
bootable fallback, which costs nothing.

## Uptime Kuma 2.x on SQLite

The `2` tag, not `latest`, because `latest` still points at the abandoned 1.x
line. Pinning the major means a deliberate `compose pull` gets fixes but can never
jump a major version unattended.

SQLite rather than the embedded MariaDB that 2.x offers. At roughly a dozen
monitors on 60-second intervals, MariaDB buys nothing and adds a database server
to the box whose whole job is not falling over. SQLite is also a single file
inside the bind mount, which is what makes restoring it trivial.

## ntfy, public rather than self-hosted

An alerting service running on the box it watches can't tell you that box has
died. Same reasoning as the help page answering on a bare IP. The topic string is
random and secret, which is the only protection ntfy.sh topics have.

## Caddy in front of everything

Without it, `status.lan:3001` and `dns.lan:8081`, which nobody remembers. With it,
every service has a name on port 80.

It also solved the foo_jean problem: Jean derives foo_jean's address from
`window.location.hostname`, so serving the UI at `music.lan` makes the browser ask
for `music.lan:8881`. A second Caddy listener fixes that without touching Jean's
build. The alternative was setting `__PLAYER_HOST__` at build time, which would
hardcode the player's address and defeat the point of having `music.lan` as an
indirection at all.

## Two layers of names

Machines get Zelda names because they're memorable and the roles map onto the
myth. Functions get dull names because those are what you reach for when
something is broken, and you shouldn't have to remember which fairy was the
router at 2am. Anyone else in the flat can use `router.lan` without being taught
the joke.

## Git as source of truth, applied by hand

Real GitOps reconciles continuously. That's wrong here: a bad push reconciling
itself onto the flat's DNS server at 3am, unattended, is a worse outcome than a
config that's a few hours stale. `git pull && sudo ./scripts/deploy.sh`, run by
someone who's watching.

Config lives in the repo, state lives in `/srv/data`. That split keeps 12 MB of
regenerable blocklist out of git and means `git clean` can't destroy query
history.

## Security updates automatic, reboots not

Debian security pocket only. Kernel, firmware and Docker are excluded, because a
bad kernel on a headless box is a bad afternoon and upgrading Docker restarts
every container.

Reboots never happen automatically. This box is the flat's DNS and doesn't get to
choose when it disappears. Monitor 11 asks you instead.

## Backup is config-only

`/srv/stack` was 29 MB, but 12 MB of that is a regenerable blocklist and most of
the rest is query history nobody will read. Since the config moved into git, the
backup is down to `.env`, `kuma.db`, and a few facts that let a rebuild match
rather than approximate.

Two copies for two failure modes. The daily local snapshot covers a bad edit,
which is much the likelier failure. The copy on the laptop covers the SSD dying.
