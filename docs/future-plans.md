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
ZTE's UI, then open `http://<current-megacable-ip>:8080` from a phone on LTE with
Wi-Fi off. **Get that address fresh, don't take it from these docs** - it has
moved twice since first being written down. `curl --interface 10.100.100.62
-s ifconfig.me` from navi returns the live one. It touches no ER605 config, so both lines stay up and nothing in Kuma goes
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
power cycle changed both lines' public IPs.

**Update 2026-09-21: less sticky than this doc used to claim.** It said Megacable
came back on the same `189.196.217.197` after that power cycle, so it was
stickier than "dynamic" implies. Both lines have since moved again with no power
cycle at all - Telmex to `187.224.28.154`, Megacable to `189.196.209.57`. Treat
both as genuinely dynamic and don't quote an address out of these docs without
checking it first. This is why monitors 6 and 7 match the ISP's reverse DNS
rather than a literal address; see [monitoring.md](monitoring.md).

Take an ER605 config backup first. The dual-WAN setup took an evening to get right.

What it buys: no more double NAT, the PS5 freed from being pinned to Telmex, and
symmetric cross-ISP monitoring. **Not** remote access - Tailscale gives you that
regardless of the answer, so don't sequence one behind the other.

## hyrule-castle, the mini PC

**Built on 2026-09-20.** Debian 13 is on it, it answers on `10.100.100.50`, and it
runs no services yet. The machine itself is documented in
[hyrule-castle.md](hyrule-castle.md); what follows is only what's still ahead of
it. It was called `ocarina` while it was still hypothetical - see
[decisions.md](decisions.md) for why the machine got renamed and why
`ocarina.lan` didn't.

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

**The 32 GB is confirmed**, three ways on 2026-09-20. That was the one assumption
the purchase rested on, and it held. Either way the RAM is maxed: one SODIMM slot,
single channel, no upgrade path.

**There is no second NVMe slot**, also now confirmed - the second M.2 is E-key and
has the WiFi card in it. Storage growth here is external, or the NAS.

**The SATA question is half-answered and worth finishing.** The BIOS shows the
controller enabled in AHCI with two ports present and empty, which means the
chipset's SATA is switched on but not that the board routes it to a physical
connector. Take the lid off and look, while the return window still allows it. If
a header is in there, a 2.5" drive is the cheap expansion path the E-key finding
took away.

**One caveat to remember before blaming anything else.** The dual NICs are Intel
i226-V, and early steppings had documented packet-drop and link-flap bugs,
discussed at length in the pfSense and OPNsense communities. These are **rev 04**
on kernel 6.12, which is the later stepping and the fixed driver era rather than
the one that generated the bug reports - so this is now a caveat rather than a
risk. If you ever do see unexplained drops, disable Energy Efficient Ethernet
before suspecting the switch or the cable:

```sh
sudo ethtool --set-eee enp3s0 eee off
```

Its only job at first is serving music, so the Windows PC can stop being a media
server.

**Phase 1, music.** Debian 13 minimal with no desktop is done. What's left is the
stack: foobar2000 + `foo_beefweb` + `foo_jean`, all Windows binaries, run under
Wine. On x86 Linux
Wine runs the Windows API natively, and two of `foo_jean`'s own design rules (a
header-only HTTP library over plain sockets, `std::` threading rather than Win32)
happen to make it unusually likely to work.

foobar2000 is a GUI app and won't start without a display, so it runs under
`Xvfb`, with output set to Null Output since the box has no speakers. Audio
reaches listeners through `foo_jean`'s stream endpoint, not the machine's own
playback. That has a design consequence worth thinking through before assuming
the remote-control UX carries over: headless, the player's own playback is
meaningless.

If Wine fails, fall back to a Windows 11 VM under KVM, roughly 2 cores and 6 GB.
Don't use a debloated ISO; unofficial builds with unclear provenance are a poor
foundation for an always-on box holding your data.

**Space budget.** The 1 TB NVMe gives about 930 GB usable. Reserve roughly 50 GB
for Linux and Docker images - of which **31 GB is already gone to swap**, which the
installer sized to match RAM for hibernation on a machine that will never
hibernate - and about 100 GB for databases and thumbnails in later phases, which
leaves around 780 GB for music against a current library of 419 GB
(349 GB sorted plus 70 GB unsorted). Comfortable, but the library is expected to
grow fast now that adding to it is enjoyable. **Treat 600 GB as the trigger** to
accelerate the NAS. The second-NVMe option is gone; the board's other M.2 socket
is E-key WiFi. Wire a disk-usage check into Uptime Kuma via a push monitor so that gets
noticed rather than discovered.

In practice the answer to this arrived early. The staged storage plan below puts
a 16 TB disk on hyrule-castle in October 2026, so the music never lives on the NVMe and
the NVMe holds only the OS, containers and databases. Keep the trigger anyway: it
is now the number that says the USB disk has become the bottleneck rather than
the NAS.

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

**Start offsite backup when the music lands, not when the NAS arrives.** That is
October 2026 under the staged plan below. Every album added after the migration
exists exactly once, on a single consumer drive in a USB enclosure, in a flat.
419 GB on Backblaze B2 is about $2.50/month, and `restic` or `rclone` on a
schedule gives a real three-copies-two-media-one-offsite position immediately.
Seeding 419 GB up a residential Mexican line is a multi-day job, so start it the
same week rather than treating it as a follow-up task.

**What changes on navi when it lands:** two values in `.env`, `MUSIC_BACKEND` and
`MUSIC_FOOJEAN`, from `10.100.100.20` to `10.100.100.50`. Both listeners need
repointing, not just the first, or streaming breaks while the UI looks fine.

**Do not repoint `ocarina.lan` at `.50` in `PIHOLE_HOSTS`.** An earlier draft of
this doc said to, on the theory that going direct is tidier. It isn't - it
bypasses Caddy, and music is the one service that has to be HTTPS because Jean
needs a secure context for `navigator.mediaSession` and `Notification`. The names
stay pointed at navi and Caddy proxies onward to `.50`; [decisions.md](decisions.md)
has why there is only one Caddy.

`PIHOLE_HOSTS` does get a new entry, for the machine itself:
`10.100.100.50 hyrule-castle hyrule-castle.lan`.

The migration to `foo_jean` alone, with beefweb dropped, collapses `MUSIC_BACKEND`
and `MUSIC_FOOJEAN` onto the same host and port - and may remove the need for the
separate `:8881` vhost entirely, since that split exists only because Jean derives
foo_jean's address from `window.location` while beefweb served the page. Check
whether a single-origin foo_jean still needs it before copying the vhost across.

**Later phases**, in this order, because four migrations at once is how
self-hosting projects die. Jellyfin (easiest real win, QuickSync handles the
transcoding). Immich (hardest; Google Takeout is genuinely painful and the ML
container is the RAM-hungriest thing on the roadmap). Files, where Syncthing is
the simpler answer and Nextcloud is the most commonly regretted piece of this
kind of stack.

## Storage, staged from October to December 2026

Storage is the expensive part of everything left on this list. Rather than wait
to afford a populated NAS in one purchase, it comes in three monthly pieces, and
the first drive does real work from the day it arrives instead of sitting in a
box waiting for the others.

**October 2026: the first 16 TB drive, hanging off hyrule-castle over USB.** A UGREEN
3.5" USB 3.0 enclosure, about 650 MXN, with its own 12 V brick rather than bus
power, which a 3.5" drive needs. The music migration lands here instead of on the
NVMe. Offsite backup starts the same week.

**November 2026: the second 16 TB drive.** It does nothing but burn-in until
December, and burning it in now rather than then is the whole point.

**December 2026: the NAS.** Both drives move inside it and the enclosure is
demoted to the burn-in rig for every disk bought after.

**USB is not a compromise at this scale.** A 16 TB 7200 RPM drive does about
260 MB/s sequential and USB 3.0 gives roughly 400 MB/s in practice, so the bridge
is not the bottleneck even during the 419 GB copy. Jean streams Opus at 256 kbps.
There are four orders of magnitude of headroom. What matters is the bridge chip,
not the speed, and that is a different question entirely - see
[decisions.md](decisions.md) for why the same reasoning does not extend to a
four-bay USB enclosure as the permanent answer.

navi already paid for the bridge lesson: its enclosure claimed an ASM1153E and is
actually a Realtek `0bda:9201`. So run `lsusb` on arrival and believe it over the
listing. A JMicron JMS578 needs `usb-storage.quirks=VID:PID:u`; Realtek and
ASMedia need nothing. SMART needs `-d sat` either way, exactly as in
[navi.md](navi.md), and a health check that forgets the flag reports success
while measuring nothing.

**Mount it at `/srv/music` and never move that path.** The Wine prefix maps drive
F to `/srv/music` and the portable foobar2000 config's `F:\` paths resolve
through it. If the USB drive is `/srv/music` in October and the NFS share is
`/srv/music` in December, foobar2000 never learns the NAS arrived. Move the path
instead and it is the same 30,441-dead-tracks failure described above.

Two guards, because a USB dropout is the realistic failure here and it should
fail loudly rather than destructively. `nofail` in fstab, so a missing drive
can't block boot. And `RequiresMountsFor=/srv/music` on the foobar2000 unit, so
it can't start against an empty directory and rescan the library into nothing.

**Watch heat and head parking.** The enclosure is sealed passive plastic with no
fan, holding an enterprise 7200 RPM drive 24/7, which is a warmer combination
than these cases are usually sold for. Stand it upright, keep it off the top of
hyrule-castle, and put SMART attribute 194 on the same Kuma push monitor as the
disk-usage check. Sustained above about 50 °C, add a fan. Separately, enclosures
in this class spin down on idle and usually don't pass `hdparm -B`/`-S` through
the bridge, so read `Load_Cycle_Count` after the first week and extrapolate
against the drive's 600k rating.

**Burn in every drive the week it arrives, not the week it gets used.** A SMART
long test plus a `badblocks -wsv` write-verify pass is 24 to 48 hours on a 16 TB
drive. Left until December, the November drive's 30-day return window closes
before it is ever powered on, which is how you find a DOA disk with no recourse.
The enclosure exists partly for this.

**The December assembly, in order, never below two copies.** Second drive into
the NAS, create the pool single-disk, copy from the first drive over USB, verify
with checksums, pull the first drive out of the enclosure, `zpool attach` to make
it a mirror. The old external drive stays untouched as the third copy until the
mirror has resilvered and scrubbed clean.

**One IronWolf Pro and one Red Pro, not two of either**, with the IronWolf Pro
bought first. Reasoning in [decisions.md](decisions.md).

**Check the price before committing.** A 16 TB IronWolf Pro listed at 19,422 MXN
on Amazon MX in September 2026, against roughly €495 in Europe for the same model,
which is a wider gap than normal import markup. Cyberpuerta is in Guadalajara and
worth comparing. On Amazon, check who the seller actually is, because bare-drive
FFP listings from third parties are a known relabel route. Compare MXN per
terabyte across 12, 14 and 18 TB while you are there; drive prices are broadly
elevated in late 2026 and 16 TB may not be the sweet spot.

## The NAS itself

A UGREEN NASync DXP4800 Plus, wiped and running TrueNAS SCALE. Four bays, all
HDD, 2× 16 TB mirrored to start and a second mirror vdev added later. SSDs buy
nothing for the bulk pool: media is large sequential reads, an HDD already does
more than 2.5 GbE carries, and 16 TB SSDs are enterprise parts at ten times the
price per terabyte. The M.2 slots take a small NVMe for databases and metadata,
where SSD speed is real and costs $60 rather than $3,000. Why this box and not a
Synology, a QNAP or a USB enclosure is in [decisions.md](decisions.md), as is
TrueNAS over Unraid.

It is a disk shelf and nothing else. hyrule-castle keeps every service - foobar2000,
Jellyfin, Immich, all of it - and the NAS runs TrueNAS alone. That is the same
separation [decisions.md](decisions.md) already requires of navi and hyrule-castle,
applied a third time.

One hard rule when it arrives: databases and caches stay local, bulk media goes to
the NAS. Immich explicitly warns against its Postgres living on a network share,
and it will corrupt.

Two drives in one chassis is not a backup. Tier by replaceability: pay to back up
photos, documents and music, don't pay to back up a film library you can re-rip.

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

## UPS and graceful shutdown

CyberPower CP1500PFCLCD, chosen for pure sine wave output. ATX supplies with
active PFC can cut out or buzz on the stepped sine that cheaper units produce.

That premise weakened when the NAS stopped being a DIY ATX build: the UGREEN, the
mini PC and navi all run from external DC bricks, which are switch-mode and far
more tolerant of a stepped waveform. Keep the pure sine unit anyway. It costs
little more, it removes a whole class of thing to debug at 3am, and it leaves
room for a future ATX machine without revisiting the decision.

NUT for graceful shutdown, with navi as the master: always on, 5 W, never touched,
and already the monitoring box, so Kuma can alert on power events. That requires
navi to be physically USB-connected to the UPS, which is why everything lives in
the kitchen.

**What goes on battery, and what only gets surge.** The unit has twelve outlets,
half of them battery-backed. Battery side: navi, hyrule-castle, the ER605, the
Telmex modem, and the main Deco. Everything else takes surge only.

The Deco is the one that's easy to forget and the one that makes the rest useful -
without it you'd have working internet during an outage and no Wi-Fi to reach it
from, since every device you'd actually pick up is wireless. Coverage during a cut
is kitchen-only; the office and bedroom Decos are on other circuits and can't be
helped.

Telmex rather than Megacable, if rationing to one line: it's the 9.3 ms path
rather than the 46.7 ms one, and the only one that accepts inbound.

**hyrule-castle goes on battery specifically so it can be shut down, not so it can
keep running.** It draws battery for the minute or two before NUT stops it, then
it's off, and `Restore AC Power Loss` brings it back when mains returns. The
alternative - surge-only, hard cut on every outage - is exactly the treatment this
doc already warns will corrupt Immich's Postgres.

At roughly 90 W across everything on the battery side, expect somewhere in the
region of 1.5-2.5 hours. Check CyberPower's runtime chart against a measured draw
rather than that estimate.

**Test it the week it arrives.** Same rule this doc applies to disks, and for a
sharper reason: the Amazon listing is marked non-returnable, and UPS units do
arrive with dead or deeply discharged batteries. Charge it fully, pull the mains
with a known load attached, confirm it holds. Finding out during the first real
outage is the expensive version.

AVR is arguably the bigger win anyway. Sags and brownouts are far more frequent
here than full cuts, and they're what quietly kills power supplies over years.

## The kitchen cable box

Currently a power strip with five oddly-shaped wall warts fighting over it, each
brick blocking the sockets either side. It is the reason hyrule-castle nearly
ended up in the office instead of the kitchen: its 60 W brick plus the travel
adapter it needs simply would not fit.

The rebuild, which also prepares for the UPS:

- The strip goes away. The UPS replaces it, and lives **outside** the box - it has
  a battery, it needs airflow, you need to read the LCD, and it wants replacing
  every few years.
- Every brick sits inside the box, plugged into its own **one-foot grounded
  extension pigtail**. The pigtail's slim plug goes to the UPS. A brick then
  occupies one UPS outlet instead of blocking three.
- Pigtails rather than a strip inside the box on purpose: it's what lets each
  device be assigned individually to a battery outlet or a surge-only one, which
  is the whole reason for buying a UPS with both.

Six pigtails covers both modems, the ER605, navi, the main Deco and
hyrule-castle. 14 AWG is heavy for a load under 1 A total, and it is stiff - 16 AWG
routes more easily in a cramped box and is still enormously overspec. ETL is
Intertek's mark and is equivalent to UL for this; what matters is that there is a
mark at all.

**Don't seal the box.** Five or six bricks in an enclosed container accumulate
heat, and the mini PC's is the biggest and warmest of them. Leave the lid ajar or
ventilate it, and don't stack bricks touching each other. Same reasoning as the
50 °C trigger on the USB enclosure above.

Never daisy-chain: one pigtail, one device, straight into a UPS outlet.

## Smaller things worth doing

A both-lines-down monitor at ntfy priority 5. Nothing currently justifies waking
you at 3am, and that priority should be reserved for something that does.

Blocking the bootstrap domains apps use to reach DoH resolvers, which forces
devices back onto Pi-hole rather than letting them route around it. It tightens
the whole network but can break apps that hard-depend on DoH, so do it
deliberately.

Moving the state backup somewhere off the flat. Right now both copies are in the
same building.

Getting a US plug head for hyrule-castle's power brick. It shipped with the
European one only, and the interim answer is a bulky travel adapter - see
[hyrule-castle.md](hyrule-castle.md). Ask the seller on the Amazon thread; it costs
a message. The pigtail rebuild makes it cosmetic rather than blocking.
