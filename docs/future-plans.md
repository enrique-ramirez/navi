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

**Lower the expectations, but the case is no longer closed.** The premise used to
be that their public address is a real routable one rather than carrier-grade NAT,
and the reverse DNS argued otherwise: `customer-GDL-CGN-217-197.megared.net.mx`,
with `CGN` in an ISP's own hostname usually meaning what it looks like.

An afternoon of probing on 2026-09-07 failed to confirm that. No `100.64/10`
appears anywhere in a TCP traceroute from `.62`, which is the one unambiguous
CGNAT marker, and the HSI connection is native dual-stack rather than DS-Lite,
which would have been carrier NAT by construction. The RFC1918 hops in between
prove nothing either way. Evidence in [network.md](network.md).

**Settle it before calling, with this test.** Plug a laptop into a spare LAN port
on the ZTE, run `python3 -m http.server 8080`, forward TCP 8080 to it in the
ZTE's UI, then open `http://189.196.217.197:8080` from a phone on LTE with Wi-Fi
off. It touches no ER605 config, so both lines stay up and nothing in Kuma goes
red, and it tests the thing you actually care about - inbound reachability -
instead of inferring it from an address. Loads, and there's a routable address
and the call is worth making. Times out, and it's CGNAT or their forwarding UI is
decorative; either way it isn't.

If you do call, ask functionally, because the frontline rep will not know the
phrase CGNAT. In order, hanging up on the first bad answer: is the public IP
exclusively mine or shared between customers, can I receive inbound connections
at all, and only then bridge mode (modo puente), whether it becomes DHCP or
PPPoE, and whether it costs extra.

Add a smaller request to the same call: the modem's admin account. The ZTE's WAN
status page has IPv4 address, gateway and DNS fields in firmware and the
`Mega_FA86` customer login doesn't render them. Not being able to read your own
WAN address is what left this unresolved.

Worth knowing either way: the address is dynamic, confirmed on 2026-09-04 when a
power cycle changed both lines' public IPs. But the DHCP lease is seven days and
it came back as the same `189.196.217.197`, so it's stickier than "dynamic"
implies. Don't build on it staying put; don't expect it to move often either.

Take an ER605 config backup first. The dual-WAN setup took an evening to get right.

What it buys: no more double NAT, the PS5 freed from being pinned to Telmex, and
symmetric cross-ISP monitoring. **Not** remote access - Tailscale gives you that
regardless of the answer, so don't sequence one behind the other.

## ocarina, the mini PC

A KINGDEL K12 with an Intel i3-N305 (Alder Lake-N, 8 cores, 32 GB DDR5, 1 TB
NVMe, dual 2.5 GbE, Intel QuickSync). Ordered 2026-09-02 as an N355; the seller
was out of stock and offered the i3-N305 in the same chassis at the same price,
plus 500 MXN refunded after delivery. Accepted 2026-09-03.

Intel rather than AMD specifically for QuickSync, which is what Jellyfin's own
docs recommend; AMD's VAAPI path is the troublesome one, with worse quality, no
AV1 decode and poor HDR tone mapping.

**The substitution costs almost nothing.** Both parts are 8-core, 8-thread
Gracemont on Intel 7, 6 MB L3, 15 W, 32 EU of graphics, single-channel memory.
The N355 turbos to 3.9 GHz against 3.8, and its iGPU clocks 1.35 GHz against
1.25: about 3% of CPU and 8% of GPU. Twin Lake is a refresh of Alder Lake-N
rather than a new architecture, so the media engine is the same one and the
QuickSync argument is untouched.

More to the point, the reason for buying up from the N100 survives intact. That
reason was 8 cores instead of 4 and 32 EU instead of 24, for Immich's
machine-learning container, which is the hungriest thing on the roadmap, and the
N305 delivers both. Being the older part it also has three more years of kernel
and driver history behind it, which for a Linux box is a mild point in its
favour.

**Verify the 32 GB on arrival, inside the return window.** Intel specifies both
chips at 16 GB maximum. That number is a validation limit rather than a hard
controller ceiling, and 32 GB SODIMMs are widely reported working on Alder
Lake-N boards, but it is not universal. The seller stated in writing on the
Amazon message thread that 32 GB is recognised and that other customers run this
configuration; keep that thread, because it is the only thing backing the claim.
Check the BIOS and `free -h` before anything else gets installed. Either way the
RAM is maxed: one SODIMM slot, single channel, no upgrade path.

**There is no second NVMe slot.** The board has two M.2 sockets, but the seller
confirmed the second one is the E-key WiFi socket, not a drive socket. E-key is
physically keyed differently from the M-key an NVMe needs, it carries a single
PCIe lane rather than four, and its 2230 standoff leaves nowhere to anchor a
2280 drive. Adapters exist; none of them are worth doing inside a chassis this
size. Storage growth here is external, or the NAS.

One question still worth asking the seller: some boxes in this class have a SATA
header and room for a 2.5" drive. If this one does, that is the cheap expansion
path.

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
accelerate the NAS. The second-NVMe option is gone; the board's other M.2 socket
is E-key WiFi. Wire a disk-usage check into Uptime Kuma via a push monitor so that gets
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
inbound. It works behind CGNAT and double NAT, so none of it is blocked on the
Megacable question above. It may also delete Navidrome from the plan: over
Tailscale, Jean plus beefweb plus `foo_jean` is the remote music server.

The step-by-step procedure is in [tailscale.md](tailscale.md), written to be
stopped and resumed at any point. The rest of this section is why it's shaped
that way.

**Install it and run `tailscale netcheck` before designing anything around it.**
That one command reports the mapped addresses, whether the mapping varies, the
nearest DERP and whether UDP works at all - which is most of what an afternoon of
ISP archaeology was trying to infer. It changes no router config and forwards no
ports, so it is cheap to try and trivial to undo.

**The dual-WAN problem to look for.** Tailscale's data plane is UDP, and
[gotchas.md](gotchas.md) records that ER605 policy routing is TCP only. So the
`.61`/`.62` trick cannot pin Tailscale to a line: its STUN probes leave by both
WANs and come back with two different mapped addresses, which Tailscale reads as
a hard NAT and answers by falling back to a DERP relay. The 9.3 ms versus 46.7 ms
gap between the lines makes it worse - an unpinned tunnel has erratic latency
even when it does connect directly.

If `netcheck` confirms it, the options in preference order: check whether current
ER605 firmware fixes the Service-Type-ALL bug (running 1.3.2 Build 20251030 as of
2026-09-07); get IPv6 delegated to the LAN, which deletes NAT traversal from the
problem rather than working around it; or fill in Link Backup with Telmex primary
and give up the aggregate bandwidth. This is the first thing that has made Link
Backup's deliberate emptiness worth revisiting.

**Test from a phone on LTE with Wi-Fi off, never from the flat's Wi-Fi.** Two
Tailscale nodes on the same LAN find each other locally and connect direct, so a
test run from inside the house is green and meaningless - the same failure mode
as the per-WAN ping monitors in gotchas.

Three things will break before reachability does. `.lan` names only resolve
remotely if Pi-hole is pushed as the tailnet's DNS with a split-DNS route, which
means Pi-hole listening on `tailscale0` and accepting queries from
`100.64.0.0/10`; its default interface setting refuses that, and this is the
likeliest failure of the lot. Advertising `10.100.100.0/24` as a subnet route is
convenient but re-exposes everything the standing rule below exists to protect,
so per-host installs are the narrower answer. And the Caddy root is already on
the MacBook, so HTTPS will look fine there while telling you nothing about a
device that doesn't have it - test from the phone.

If browser access without installing a client is ever needed, Cloudflare Tunnel
is the fallback. Read its free-tier terms first: section 2.8 prohibits streaming
significant video, so it would cover photos and files but not Jellyfin.

Standing rule regardless: never port-forward SSH, beefweb or `foo_jean` on the
ER605. One of them has no authentication at all and the other rewrites files in
the library. Tailnet ACLs are that same rule in a different place, so write them
before the first remote connection - "everyone on the tailnet" includes every
phone you will ever lose.

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
