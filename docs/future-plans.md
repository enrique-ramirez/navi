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

**The SATA question stays open, and no longer urgently.** The BIOS shows the
controller enabled in AHCI with two ports present and empty, which means the
chipset's SATA is switched on but not that the board routes it to a connector.
The return window has closed and the box is being kept, so this is curiosity now.
If a header is in there it is still the cheap expansion path the E-key finding
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

**Phase 1, music. Done on 2026-09-22**, except `foo_jean` itself.

foobar2000 v2.25.10 x64 runs headless under Wine 10.0 and Xvfb as a systemd
service, with the library, every playlist, all play counts and the Last.fm session
carried over from the Windows install. 30,429 tracks. Full detail, including the
several ways stopping it can go wrong, is in
[hyrule-castle.md](hyrule-castle.md).

Wine needed no tricks. It runs the Win32 API natively on x86, foobar2000 is a
plain desktop app, and the two `foo_jean` design rules this doc noted - a
header-only HTTP library over plain sockets, `std::` threading rather than Win32 -
should carry over as predicted. That remains unproven until the component is
actually installed.

What is left of the original phase-1 plan: the stack:

**`foo_beefweb` is out of the plan.** Jean started as a beefweb theme with
`foo_jean` alongside it for the parts beefweb couldn't do, and is migrating to
`foo_jean` alone. Earlier versions of this doc listed both; only one component
gets installed.

**64-bit, settled by the component.** `plugins/fb2k/foo_jean.sln` in the jean repo
has exactly two configurations, `Debug|x64` and `Release|x64`, and the vcxproj
declares no `Win32` platform at all. So foobar2000 must be the v2 **x64** build,
and since plugin and host architecture have to match and nothing 32-bit remains in
the stack, **no `dpkg --add-architecture i386` and no `wine32`.** That removes the
fiddliest part of Wine on Debian.

**It needs foobar2000 2.0 or newer, and this is a hard floor.** `foo_jean`'s
`ARCHITECTURE.md` records that the media library API depends on `metadb_v2` and
that `library_callback_v2_dynamic` registers against `library_manager_v4`, whose
`get()` crashes when absent. Development and measurements are against 2.25.x.
Install a v2 x64 build, not v1.

Debian trixie carries `wine 10.0~repack-6` in `main`, which is recent enough to
start with; `xvfb` and `contrib` (for `winetricks`, if needed) are both available.
Reach for the WineHQ repo only if something specific fails, rather than by
default.

On x86 Linux
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

**Migrating the library. Started 2026-09-21, ahead of schedule and deliberately.**
The sorted library is now on hyrule-castle's NVMe at `/srv/music/library`, copied
directly from the Toshiba over USB rather than over the network.

This contradicts the line further up that says the music never lives on the NVMe.
That line assumed the October disk would arrive before the library needed a home.
It hadn't, and until this copy the library existed in **exactly one place** - a
drive this doc itself calls untrusted, with 48,541 power-on hours on it. Three more
weeks of single-copy exposure was the worse bet. The price is one extra local copy
in October, NVMe to USB, a couple of unattended hours.

The unsorted `sort` pile - now 79 GB, not the 70 recorded below - was deliberately
left behind, pending a Mac-side sorting workflow. **It remains single-copy on the
old drive**, which is a known and accepted exposure rather than an oversight.

Measured on the day: 349 GB, 37,231 files in `Musica`; 37,091 transferred after
excluding macOS `._*` / `.DS_Store` and Windows `Thumbs.db` / `desktop.ini`.
373.77 GB at 86.89 MB/s in 1:08:22 over USB 3.0 with UASP.

**Verified, not assumed.** A second pass with `rsync -rltc --dry-run
--itemize-changes` re-read all 349 GB from both copies and compared by checksum,
taking 61 minutes at 97 MB/s and reporting **zero differences across all 37,091
files**. Matching sizes and counts would have proved nothing - corruption comes
back the right length, which is the entire reason this doc demands checksums.

`-rltc` rather than the `-avc` this doc used to specify: `-a` on a FAT32 source
generates permission and ownership noise for attributes FAT does not have.

What that pass proves is that the **copy is faithful**. It cannot prove the
**source was good** - a file that rotted on the Toshiba years ago now has an
identical rotten twin, and rsync calls that a match. FLAC stores an MD5 of its own
decoded audio, so `flac -t` is the check that catches that. It was run on
2026-09-21 across all 5,037 FLAC files, 141.4 GB.

**There is no rot. Not one file.** Zero MD5 mismatches, zero mid-stream sync
losses. Five and a half years on that drive cost nothing.

What it did find, all of it pre-existing and none of it caused by the copy:

| | files | albums | |
|---|---|---|---|
| clean | 4,479 | | |
| ID3 tags only | 519 | 48 | audio complete, fixed |
| truncated | 39 | 5 | real loss, left alone |

**The 519 were cosmetic.** ID3v2 on the front and ID3v1 on the back of a FLAC,
written years ago by something treating FLAC as MP3. The audio was complete; the
decoder simply ran off the end of the stream into the trailer. Stripped with
`mutagen.id3.delete(p, delete_v1=True, delete_v2=True)` after proving on a copy
that audio MD5, Vorbis comments and embedded art all survive untouched. All 519
verify `CLEAN` afterwards. About 1.2 MB of junk removed. Joaquin Sabina (16
albums), Stevie Wonder (7) and CCR (6) were most of it.

**The 39 are genuinely short**, 6 ms to 763 ms missing from the end of each track,
across five albums - every track in each affected. All are obscure 2009-2012 indie
releases, which reads like incomplete downloads from that era rather than anything
the drive did:

| album | worst track |
|---|---|
| `S/Spouds, The/(2012) Paxil` | 763 ms, all 11 tracks |
| `W/We Only Said/(2009) We Only Said` | 740 ms, all 10 tracks |
| `K/KYST/(2011) Waterworks` | 615 ms, all 8 tracks |
| `E/Ewa Gigon/(2011) Moonflowers` | 92 ms, all 8 tracks |
| `R/Rachael/(2011) Summer Dope` | 66 ms, both tracks |

Left deliberately unfixed. Stripping their ID3 would not make them pass, and
leaving them means a library-wide `flac -t` now returns **exactly 39 known errors
in 5 named albums and nothing else** - a set small enough to stay meaningful
rather than 558 errors nobody reads.

MP3 has no equivalent integrity field, so the other ~32,000 files cannot be
checked this way at all.

**The source drive.** A Toshiba MQ01UBD100, FAT32, volume label `FALCHION`. SMART
was clean where it counts - zero reallocated, zero pending, zero offline
uncorrectable - against 48,541 power-on hours and 7,846 loaded hours, so roughly
84% of its powered life had the heads parked. Zero reallocations at that age is a
healthy old drive rather than a dying one, but it is well past the duty cycle a
2.5" portable is designed around.

**It is a native-USB drive, so it cannot be shucked.** The USB 3.0 interface is on
the drive's own PCB - `lsusb` reports Toshiba `0480:0201`, not a third-party bridge
chip. If that interface fails the platters are unreachable without a recovery
service, even though the data is intact. That is a different and worse failure mode
than a normal disk in an enclosure, and it is a reason not to let it be the only
copy of anything.

**The original three rules still hold.** 419 GB - now 428 - lives on an old,
untrusted external drive. Three rules, all load-bearing. Check SMART before copying, because
reallocated or pending sectors mean `ddrescue` is a better tool than a plain copy.
Verify with checksums, because a failing drive returns silently corrupted data on
read and you'd find the damage years later; use TeraCopy or `rsync -avc`, never
Explorer drag-and-drop. And don't erase the old drive: until the NAS exists it's
the only second copy of an irreplaceable collection.

Keep unsorted files out of the tree foobar2000 watches. Every count Jean reports
derives from the `#Jean Library` autoplaylist, which mirrors the Media Library, so
a playlist polluted with unsorted material makes every figure wrong. Use
`/srv/music/library` (watched) and `/srv/music/inbox` (not).

**The `F:\` claim in earlier versions of this doc was wrong**, and the drive-letter
mapping it prescribed does not do what it said. Checked against the real
`metadb.sqlite` on 2026-09-21: all 30,446 entries are `file-relative://`, and not
one holds an absolute path.

```
0+file-relative://..\Musica\#\10cc\(1975) The Original Soundtrack\01. ...
```

| scheme | count | |
|---|---|---|
| `file-relative://` | 30,446 | every entry |
| under `..\Musica\` | 30,442 | the library |
| under `..\foo_jean-test\` | 4 | Jean's sample files |

So the constraint is not a drive letter. **`Musica` has to be a sibling of the
directory holding `foobar2000.exe`**, because `..\` resolves relative to the
install in portable mode. `sort` appears zero times, which means the unsorted pile
is already outside the watched tree without anyone having to arrange it.

The layout that satisfies this, and survives October:

```
/srv/fb2k/foobar2000/          the portable install
/srv/fb2k/Musica -> /srv/music/library      symlink
```

foobar2000 asks for `..\Musica\`, Wine follows the symlink. When `/srv/music`
becomes the USB disk's mount point in October, the symlink already points there
and **nothing changes** - which is a better property than the drive-letter scheme
ever had. Keep the install out of `/srv/music` itself, or it disappears when that
path is remounted.

Get the sibling relationship wrong and 30,442 tracks come up dead.

**Start offsite backup when the music lands, not when the NAS arrives.** That is
October 2026 under the staged plan below. Every album added after the migration
exists exactly once, on a single consumer drive in a USB enclosure, in a flat.
419 GB on Backblaze B2 is about $2.50/month, and `restic` or `rclone` on a
schedule gives a real three-copies-two-media-one-offsite position immediately.
Seeding 419 GB up a residential Mexican line is a multi-day job, so start it the
same week rather than treating it as a follow-up task.

**What changes on navi when it lands:** `MUSIC_BACKEND` in `.env` becomes
`10.100.100.50:8881`. It is the only music value now. See the note on
`MUSIC_FOOJEAN` below.

**Do not repoint `ocarina.lan` at `.50` in `PIHOLE_HOSTS`.** An earlier draft of
this doc said to, on the theory that going direct is tidier. It isn't - it
bypasses Caddy, and music is the one service that has to be HTTPS because Jean
needs a secure context for `navigator.mediaSession` and `Notification`. The names
stay pointed at navi and Caddy proxies onward to `.50`; [decisions.md](decisions.md)
has why there is only one Caddy.

`PIHOLE_HOSTS` does get a new entry, for the machine itself:
`10.100.100.50 hyrule-castle hyrule-castle.lan`.

The migration to `foo_jean` alone, with beefweb dropped, collapsed `MUSIC_BACKEND`
and `MUSIC_FOOJEAN` onto the same host and port. It also removed the need for the
separate `:8881` vhost, which existed only because Jean reached foo_jean on a
second port while beefweb served the page. Checked on 2026-09-24: foo_jean now
serves Jean at `/`, and Jean calls the API on the page's own origin. So
`MUSIC_FOOJEAN` and the vhost are gone, and old `/jean/` URLs redirect to `/`.

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

**The US plug head is not coming.** The seller conversation closed before it was
asked for, so the brick keeps its European head and the travel adapter. That is
fine: the pigtail rebuild above makes the adapter's bulk irrelevant, which was the
only problem it ever caused.
