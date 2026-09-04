# What's next

Roughly in order. `tatl` and the Megacable call are small; the rest are projects.

The case is done: fitted with the copper block and MX-4 on 2026-09-03, and it
dropped peak load temperature from 83.2 °C to 51.1 °C with no throttling. Numbers
are in [navi.md](navi.md).

## tatl, the second Pi-hole

The old Pi 1 Model B has a job. Two blocking resolvers give real failover without
the leak a public secondary would introduce, and more usefully it means navi can
be rebooted or upgraded without taking the flat's DNS down.

It fits: Pi-hole still ships an ARMv6 build and needs 512 MB RAM and 2 GB disk.
Two things to check before buying parts. A Pi 1 Model B has either 256 MB or
512 MB depending on board revision, and it takes a full-size SD card, not microSD.
Bare-metal install, not Docker, since there are no ARMv6 container images.

Syncing is `nebula-sync`, run as a container on navi. The older `gravity-sync` is
archived and incompatible with Pi-hole v6.

About $20 of parts: full-size SD card, micro-USB PSU, ethernet cable.

Do it after navi has been stable for a while. Building both at once means
debugging two boxes and a sync tool at the same time with no way to tell which is
lying.

## Call Megacable about bridge mode

Their public address is a real routable one, not carrier-grade NAT, so bridge mode
would probably put a public IP straight onto the ER605's WAN2.

Ask specifically: bridge mode (modo puente), whether you get a routable public
address or CGNAT, whether it becomes DHCP or PPPoE, and whether it costs extra. If
the answer is CGNAT, it's not worth doing.

Take an ER605 config backup first. The dual-WAN setup took an evening to get right.

What it buys: no more double NAT, the PS5 freed from being pinned to Telmex, and
symmetric cross-ISP monitoring.

## ocarina, the mini PC

A KINGDEL N355 (Twin Lake, 8 cores, 32 GB DDR5, 1 TB NVMe, dual 2.5 GbE, Intel
QuickSync). Intel rather than AMD specifically for QuickSync, which is what
Jellyfin's own docs recommend; AMD's VAAPI path is the troublesome one, with worse
quality, no AV1 decode and poor HDR tone mapping.

N355 over the cheaper N100 for the headroom: 8 cores instead of 4, 32 EU instead
of 24. That margin is for Immich's machine-learning container, which is the
hungriest thing on the roadmap. The RAM is already maxed and there's no upgrade
path, since the board has a single SODIMM slot capped at 32 GB.

**One caveat to remember before blaming anything else.** The dual NICs are Intel
i226-V, and early steppings had documented packet-drop and link-flap bugs,
discussed at length in the pfSense and OPNsense communities. Later revisions fixed
it and recent kernels are fine. If you ever see unexplained drops, disable Energy
Efficient Ethernet before suspecting the switch or the cable:

```sh
sudo ethtool --set-eee enp1s0 eee off
```

Its only job at first is serving music, so the Windows PC can stop being a media
server.

**Phase 1, music.** Debian 13 minimal, no desktop. The stack is foobar2000 +
`foo_beefweb` + `foo_jean`, all Windows binaries, run under Wine. On x86 Linux
Wine runs the Windows API natively, and two of `foo_jean`'s own design rules (a
header-only HTTP library over plain sockets, `std::` threading rather than Win32)
happen to make it unusually likely to work.

foobar2000 is a GUI app and won't start without a display, so it runs under
`Xvfb`, with output set to Null Output since the box has no speakers. Audio
reaches listeners through `foo_jean`'s stream endpoint, not the machine's own
playback. That has a design consequence worth thinking through before assuming
the remote-control UX carries over: headless, the player's own playback is
meaningless.

You can de-risk all of this before the hardware arrives by running a Debian VM on
the Windows PC. It's x86, so the test is valid.

If Wine fails, fall back to a Windows 11 VM under KVM, roughly 2 cores and 6 GB.
Don't use a debloated ISO; unofficial builds with unclear provenance are a poor
foundation for an always-on box holding your data.

**Space budget.** The 1 TB NVMe gives about 930 GB usable. Reserve roughly 50 GB
for Linux and Docker images and about 100 GB for databases and thumbnails in later
phases, which leaves around 780 GB for music against a current library of 419 GB
(349 GB sorted plus 70 GB unsorted). Comfortable, but the library is expected to
grow fast now that adding to it is enjoyable. **Treat 600 GB as the trigger** to
either fit a second NVMe (ask the seller whether the slot exists) or accelerate
the NAS. Wire a disk-usage check into Uptime Kuma via a push monitor so that gets
noticed rather than discovered.

**Migrating the library.** 419 GB currently lives on an old, untrusted external
drive. Three rules, all load-bearing. Check SMART before copying, because
reallocated or pending sectors mean `ddrescue` is a better tool than a plain copy.
Verify with checksums, because a failing drive returns silently corrupted data on
read and you'd find the damage years later; use TeraCopy or `rsync -avc`, never
Explorer drag-and-drop. And don't erase the old drive: until the NAS exists it's
the only second copy of an irreplaceable collection.

Keep unsorted files out of the tree foobar2000 watches. Every count Jean reports
derives from the `#Jean Library` autoplaylist, which mirrors the Media Library, so
a playlist polluted with unsorted material makes every figure wrong. Use
`/srv/music/library` (watched) and `/srv/music/inbox` (not).

The portable foobar2000 config holds `F:\` paths. Map the music directory to
drive F in the Wine prefix and the library resolves untouched:

```sh
ln -s /srv/music ~/fb2k/dosdevices/f:
```

Get that wrong and 30,441 tracks come up dead.

**Start offsite backup when the music lands, not when the NAS arrives.** Every
album added after the migration exists exactly once, on a consumer NVMe, in a
flat. 419 GB on Backblaze B2 is about $2.50/month, and `restic` or `rclone` on a
schedule gives a real three-copies-two-media-one-offsite position immediately.

**What changes on navi when it lands:** two values in `.env`, `MUSIC_BACKEND` and
`MUSIC_FOOJEAN`, from `10.100.100.20` to `10.100.100.50`. Both listeners need
repointing, not just the first, or streaming breaks while the UI looks fine. Then
`PIHOLE_HOSTS` so `ocarina.lan` points at `.50` directly instead of at navi's
proxy.

**Later phases**, in this order, because four migrations at once is how
self-hosting projects die. Jellyfin (easiest real win, QuickSync handles the
transcoding). Immich (hardest; Google Takeout is genuinely painful and the ML
container is the RAM-hungriest thing on the roadmap). Files, where Syncthing is
the simpler answer and Nextcloud is the most commonly regretted piece of this
kind of stack.

## Remote access, when it's wanted

Tailscale. No port forwarding, no DMZ, no DDNS, and it dissolves the
Telmex-only-accepts-inbound asymmetry entirely, because nothing ever accepts
inbound. It may also delete Navidrome from the plan: over Tailscale, Jean plus
beefweb plus `foo_jean` is the remote music server.

If browser access without installing a client is ever needed, Cloudflare Tunnel
is the fallback. Read its free-tier terms first: section 2.8 prohibits streaming
significant video, so it would cover photos and files but not Jellyfin.

Standing rule regardless: never port-forward SSH, beefweb or `foo_jean` on the
ER605. One of them has no authentication at all and the other rewrites files in
the library.

## NAS, eventually

Four bays, all HDD, starting with 2× 16 TB mirrored and a second pair added later.
SSDs buy nothing here: media is large sequential reads, an HDD already does more
than 2.5 GbE carries, and 16 TB SSDs are enterprise parts at ten times the price
per terabyte. Put a small NVMe in for databases and metadata, where SSD speed is
real and costs $60 rather than $3,000.

DIY with TrueNAS SCALE or Unraid rather than Synology, which has turned hostile
with drive lock-in and escalating software restrictions.

One hard rule when it arrives: databases and caches stay local, bulk media goes to
the NAS. Immich explicitly warns against its Postgres living on a network share,
and it will corrupt.

Two drives in one chassis is not a backup. Tier by replaceability: pay to back up
photos, documents and music, don't pay to back up a film library you can re-rip.

## UPS and graceful shutdown

CyberPower CP1500PFCLCD, chosen for pure sine wave output. ATX supplies with
active PFC (which a DIY NAS will likely have) can cut out or buzz on the stepped
sine that cheaper units produce.

NUT for graceful shutdown, with navi as the master: always on, 5 W, never touched,
and already the monitoring box, so Kuma can alert on power events. That requires
navi to be physically USB-connected to the UPS, which is why everything lives in
the kitchen.

## Smaller things worth doing

A both-lines-down monitor at ntfy priority 5. Nothing currently justifies waking
you at 3am, and that priority should be reserved for something that does.

Blocking the bootstrap domains apps use to reach DoH resolvers, which forces
devices back onto Pi-hole rather than letting them route around it. It tightens
the whole network but can break apps that hard-depend on DoH, so do it
deliberately.

Moving the state backup somewhere off the flat. Right now both copies are in the
same building.
