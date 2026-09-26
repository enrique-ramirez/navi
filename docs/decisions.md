# Why it's built this way

Settled, with reasons, so they don't get relitigated.

## navi and hyrule-castle stay separate machines

hyrule-castle will run the media services. It doesn't also run DNS, for three reasons.

It's the machine that gets updated, restarted and actively developed against. `foo_jean` is built and tested there, so crashes are expected. House DNS can't live on a box with that duty cycle.

The monitor must not share a failure domain with what it monitors. If Kuma ran on the media server, a failure there would take out both the service and the thing that would have told you, which reproduces the exact silent-failure bug this box was bought to fix.

And the Pi was already paid for. Consolidating recovers nothing.

## i3-N305 instead of the N355 that was ordered

The N355 was out of stock. The seller offered an i3-N305 in the same chassis at the same price with 500 MXN back, and that was accepted rather than restarting the search, because DDR5 prices in late 2026 made the bundled 32 GB most of the value of the order.

It is close to a lateral move. Same 8 Gracemont cores, same 32 EU, same 15 W, same media engine, roughly 3% of CPU clock and 8% of GPU clock given up. The argument for buying above an N100 was cores and execution units for Immich, and the N305 has all of them. Details in [future-plans.md](future-plans.md).

**The 32 GB was confirmed on 2026-09-20**, three ways: the BIOS, Windows before it was wiped, and `free -h`. That was the one assumption the purchase rested on and it held. Details in [hyrule-castle.md](hyrule-castle.md).

Still open: confirm the 500 MXN refund lands.

## TrueNAS SCALE, not Unraid

Unraid is the obvious fit for buying disks one at a time, which is exactly what the staged plan in [future-plans.md](future-plans.md) does. That argument lost anyway.

The target layout is 2× 16 TB mirrored, then a second mirror vdev. ZFS does that cleanly and it needs none of Unraid's incremental flexibility, so the flexibility would be paid for and not used.

What decides it is the failure this whole project keeps circling: a failing drive returning silently corrupted data on a read, discovered years later. ZFS checksums every block and scrubs on a schedule, so the corruption surfaces while there is still a good copy to repair from. Unraid's default parity detects nothing until asked. TrueNAS is also free where Unraid is a paid licence.

## UGREEN running TrueNAS, not Synology, QNAP, or a USB enclosure

Synology is out on exit cost, not feature bloat. Declining to install Synology Photos costs nothing; drive lock-in on recent models and a track record of removing features from hardware people already own is the real problem, and it is the same test [hosting.md](hosting.md) applies to every other vendor here. QNAP is out on security, having been the target of repeated ransomware campaigns against internet-facing units.

The UGREEN NASync DXP4800 Plus is an x86 machine: four bays, dual 2.5 GbE, M.2 slots, and a vendor that supports installing another OS rather than fighting it. Its own software is irrelevant because it gets wiped on day one, so the bet is only on the sheet metal and the PSU, which is the right size of bet for a new entrant. DIY with a Jonsbo N4 and an ITX board is cheaper and more repairable, and was rejected because the interesting work here is software and four migrations are already queued behind this one.

A multi-bay USB enclosure is the tempting cheap answer, around 4,000 MXN against 16,000, and it is the wrong one. The price gap is honest: it buys sheet metal, a PSU and one USB-to-SATA bridge with a port multiplier, where the UGREEN buys a CPU, RAM, networking and direct SATA access. Three things follow. Its RAID modes live in the bridge in a proprietary on-disk format, so the array is readable only by an identical enclosure, which is unrecoverable lock-in in the one layer that cannot afford any. Every bay shares a single 5 Gbps link, which is fine for streaming and bad during a resilver. And USB bridges reset, dropping a disk off the bus long enough for ZFS to suspend the pool - an acceptable, reversible risk on one disk for three months, not the permanent home for irreplaceable photos.

There is no third option. hyrule-castle has no PCIe slot and its second M.2 is E-key WiFi, so a real HBA cannot be added - confirmed on 2026-09-20 by the WiFi card being present and working, rather than taken on the seller's word. It is USB or a separate machine.

## One IronWolf Pro and one Red Pro, not two of either

On paper they are the same drive: 7200 RPM, CMR, helium-sealed, 550 TB/year rated, five-year warranty. Backblaze's figures put both vendors' modern 16 TB helium drives under 1% AFR, and the WD SMR affair was Red non-Pro at 2-6 TB, which has nothing to do with either of these.

Buying one of each decorrelates firmware bugs and batch defects, which is the failure a mirror cannot survive: two identical disks under identical load dying days apart. ZFS does not care that the halves are different models as long as the capacities match. Buying them a month apart, which the staged plan does for cash flow reasons, decorrelates manufacturing batches on top of that.

The IronWolf Pro is bought first because it includes three years of Seagate Rescue data recovery and WD offers no equivalent, and the first drive is the one that spends October to December 2026 in a passive plastic enclosure holding the only fast copy of the library. The cost is a few watts, a few degrees and some noise, in a flat. That is the trade.

## Pi-hole, not AdGuard Home

AdGuard is easier to run. Pi-hole has a bigger community, more knobs, and there's nothing AdGuard does that Pi-hole can't reach with modest effort.

v6 was a rough release (it dropped lighttpd and PHP, broke every third-party dashboard, and shipped a post-release fixes blog three days later) but that transition is over and v5 is dead. We arrived after the pain.

## No secondary DNS

The tempting move is handing out `1.1.1.1` alongside Pi-hole so the flat degrades gracefully. It's the wrong call: clients fall back to the public resolver whenever navi is merely slow, so ads appear intermittently and unpredictably, and you can never tell whether blocking is working.

Instead, Pi-hole is the only resolver, and monitor 8 watches it. `tatl` will eventually provide real failover with two blocking resolvers, which is the combination a public secondary can't give you.

## HaGeZi Multi NORMAL, one list, not Pro

Replaced StevenBlack's 78,609 domains with HaGeZi's 190,433.

One list rather than several. Pi-hole deduplicates, so a second list adds little coverage but destroys attribution: when a site breaks you no longer know which list did it, and removing one may not fix it. Stacking blocklists is the most common cause of Pi-hole maintenance pain.

NORMAL rather than PRO because Pro blocks error and crash trackers, including Firebase. On Android that's push notifications, remote config and auth, not just crash reporting. The failure mode is notifications silently not arriving, which nobody attributes to DNS for weeks. Escalating is a one-word change in `.env` if you decide you want it.

HaGeZi blocks ad-serving hosts rather than corporate apexes. `criteo.com` resolves, `static.criteo.net` doesn't. That's more surgical than StevenBlack's approach and breaks fewer opt-out pages.

## SSD, not the SD card

Pi-hole and Kuma both write constantly. The SSD gives 339/227 MB/s against maybe 20 MB/s from the card, and doesn't wear out. The card stays as a complete bootable fallback, which costs nothing.

## Uptime Kuma 2.x on SQLite

The `2` tag, not `latest`, because `latest` still points at the abandoned 1.x line. Pinning the major means a deliberate `compose pull` gets fixes but can never jump a major version unattended.

SQLite rather than the embedded MariaDB that 2.x offers. At roughly a dozen monitors on 60-second intervals, MariaDB buys nothing and adds a database server to the box whose whole job is not falling over. SQLite is also a single file inside the bind mount, which is what makes restoring it trivial.

## ntfy, public rather than self-hosted

An alerting service running on the box it watches can't tell you that box has died. Same reasoning as the help page answering on a bare IP. The topic string is random and secret, which is the only protection ntfy.sh topics have.

## Caddy in front of everything

Without it, `status.lan:3001` and `dns.lan:8081`, which nobody remembers. With it, every service has a name on port 80.

**One Caddy, and it stays on navi.** When hyrule-castle arrived the obvious move was a second Caddy there, so service traffic would go straight to the box holding the data instead of being proxied through a Pi. That was wrong twice over.

A single centralised ingress is the mainstream pattern, not a compromise - a Kubernetes cluster runs one ingress controller in front of everything, for the same reason. Two Caddyfiles with overlapping concerns is two things to keep in step and one of them will rot.

The performance argument for splitting was weaker than it looked. Every Deco backhauls to the kitchen, so living-room and bedroom clients cross the same number of hops either way; only a client in the same room as the server would have benefited, and that stopped mattering once hyrule-castle moved to the kitchen anyway. The availability argument was worse than weak - it was double counting. Every service name resolves through Pi-hole, which runs on navi, so navi being down already means `music.lan` doesn't resolve regardless of where Caddy lives. Splitting would have moved which component fails, not removed a failure.

And one Caddy means one internal CA, one root installed on the TVs and the MacBook, and no copying a CA private key onto a second machine.

Revisit only if measured: 4K direct-play streams saturating a Pi 4's TLS throughput, or DNS latency tracking video playback. Moving Caddy later is an evening, not a rewrite.

It also solved the foo_jean problem, while beefweb served the page: Jean derived foo_jean's address from `window.location.hostname`, so serving the UI at `music.lan` made the browser ask for `music.lan:8881`. A second Caddy listener fixed that without touching Jean's build. That listener was retired on 2026-09-24, when foo_jean started serving Jean itself on one origin and there was no second port left to reach.

## Docker arrives with Jellyfin, not with foobar2000

hyrule-castle's first service runs on the host under systemd. Docker gets installed when the second one does.

foobar2000 under Wine is a bad container candidate and a good systemd unit. No maintained image exists, so it would be a Dockerfile to own forever. Debugging a Win32 GUI app, under Wine, under Xvfb, under a container is three layers of indirection on the box where `foo_jean` is actively developed and restarted constantly. And the `F:\` path mapping is already the part [future-plans.md](future-plans.md) warns will cost you 30,441 dead tracks if it goes wrong; a bind mount underneath it adds a second place for that to happen. The one thing that normally forces containers here - audio device passthrough - doesn't apply, because `foo_jean` streams over HTTP and the player's own output is Null Output.

Those docs already assumed this without saying so: `RequiresMountsFor=/srv/music` is described as going on "the foobar2000 unit", and the Wine prefix maps drive F through a symlink in a home directory. Both describe a host process.

Docker earns its place later and specifically. Immich is distributed as Compose and its ML container is the hungriest thing on the roadmap. Jellyfin's official image makes QuickSync a `--device /dev/dri` rather than a hand-maintained native install. And `mem_limit` matters once a photo import shares a box with a live audio stream - the same argument [navi.md](navi.md) makes for enabling memory cgroups so a runaway container can't take DNS down.

Deferring is not just neutral. Docker brings a daemon and its own iptables chains, and there is a plan to restrict `foo_jean`'s port to navi with nftables. Installing Docker before it is needed means debugging that interaction earlier than necessary, on the box that is supposed to be playing music.

## Two layers of names

The machine is `hyrule-castle`; the things on it are `music.lan`, `films.lan`, `photos.lan`, `files.lan`. Earlier drafts named the machine `ocarina`, which broke the rule by picking a Zelda name to describe a function - and then aged badly the moment the roadmap gave that box a film library and a photo library. `ocarina.lan` survives as an alias of `music.lan`, where it always belonged. Renaming the machine cost nothing because DNS maps names to addresses independently of hostnames.

Machines get Zelda names because they're memorable and the roles map onto the myth. Functions get dull names because those are what you reach for when something is broken, and you shouldn't have to remember which fairy was the router at 2am. Anyone else in the flat can use `router.lan` without being taught the joke.

## Git as source of truth, applied by hand

Real GitOps reconciles continuously. That's wrong here: a bad push reconciling itself onto the flat's DNS server at 3am, unattended, is a worse outcome than a config that's a few hours stale. `git pull && sudo ./scripts/deploy.sh`, run by someone who's watching.

Config lives in the repo, state lives in `/srv/data`. That split keeps 12 MB of regenerable blocklist out of git and means `git clean` can't destroy query history.

## Security updates automatic, reboots not

Debian security pocket only. Kernel, firmware and Docker are excluded, because a bad kernel on a headless box is a bad afternoon and upgrading Docker restarts every container.

Reboots never happen automatically. This box is the flat's DNS and doesn't get to choose when it disappears. Monitor 11 asks you instead.

## The status panel shows, it doesn't tell

The vitals on `help.lan` are a static JSON written by a timer, not an endpoint. `host-status.sh` runs as root, and the gap between "a page showing root's view of the box" and "a page letting the LAN ask root questions" is the whole security model. Same rule that keeps a deploy button off that page.

It also doesn't alert, and doesn't tail the journal. Kuma alerts; duplicating that would mean two systems with two opinions about what's wrong. A log tail would be an information-disclosure surface that grows every time some service logs a token, in exchange for a worse version of `journalctl -u`. What's shown instead is derived unit state, which can't leak a secret.

The one thing it does that nothing else did: notice that `navi-backup.timer` has stopped running. Full reasoning in [monitoring.md](monitoring.md).

## Backup is config-only

`/srv/stack` was 29 MB, but 12 MB of that is a regenerable blocklist and most of the rest is query history nobody will read. Since the config moved into git, the backup is down to `.env`, `kuma.db`, and a few facts that let a rebuild match rather than approximate.

Two copies for two failure modes. The daily local snapshot covers a bad edit, which is much the likelier failure. The copy on the laptop covers the SSD dying.

The 90 days of vitals history in `/srv/data/history` are deliberately left out too. It's up to 22 MB against a backup measured in KB, and losing it costs a chart, not a rebuild.

## Vitals history as files, not a metrics stack

Each tile on the panel opens 24 hours, 7 days or 90 days of history. That is the textbook job for Prometheus and Grafana, or Netdata, and each of those is a resident service with its own dashboard, its own port and its own memory footprint, on the box whose whole job is not falling over.

What was built instead is the panel's existing shape stretched over time. `host-status.sh` already had every number; it appends them as one CSV line per sample to a file per day. `host-history.sh` runs every 5 minutes, rolls those up into three static JSON files, and deletes days past 90. The page draws them as plain SVG. No daemon, no database, no endpoint, and retention is `rm`.

Two things the off-the-shelf tools would have got wrong for this box. Buckets keep their max next to their average, because an hourly average hides the temperature spike you opened the chart to find. And downtime comes from the samples, not from a scraper noticing a target vanish: the scraper lives on the same box, so it can't tell you navi was off.
