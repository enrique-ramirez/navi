# hyrule-castle

The mini PC. It holds the services.

navi runs the network; this box runs everything you actually use. Right now that
is nothing at all - it was installed on 2026-09-20 and has no services on it yet.
foobar2000 under Wine is first, then Jellyfin, then Immich, then file sync, in
that order and no faster. [future-plans.md](future-plans.md) has the reasoning.

## The name

The machine is `hyrule-castle`. The services are `music.lan`, `films.lan`,
`photos.lan`, `files.lan`, and whatever comes after.

This is the two-layer rule from [network.md](network.md) applied properly for the
first time. Earlier drafts of these docs called the machine `ocarina`, which
blurred the layers: `ocarina` is a Zelda name chosen to describe a function, and
this box stopped being a music server the moment the roadmap grew a photo library
and a film library. A castle holds things. That ages better.

`ocarina.lan` still resolves and still means the music player. It is a service
name now, an alias of `music.lan`, and nothing that points at it needs to change
- including the TV homepage plan and the Caddy vhosts.

## Hardware

KINGDEL K12. Intel i3-N305, Alder Lake-N, 8 cores, 8 threads, 15 W, 32 EU of
Xe graphics with QuickSync. Bought for Jellyfin transcoding and Immich's
machine-learning container; the substitution from the ordered N355 is argued in
[decisions.md](decisions.md).

| | |
|---|---|
| RAM | 32 GB DDR5-4800, single SK Hynix SODIMM, `HMCG88AEBSA092N` |
| Disk | Lexar SSD NM610 PRO 1 TB NVMe, 932 GB usable, serial `QGC915H008131P1137` |
| NICs | 2× Intel I226-V `[8086:125c]` rev 04 |
| WiFi | combo card in the E-key M.2 socket |
| BIOS | AMI Aptio Setup 2.22.1293, 2025 |
| PSU | XinsPower `A653-1205000I`, 12.0 V ⎓ 5.0 A, 60 W, centre-positive |

**The 32 GB is real and it is maxed.** Intel specifies both this chip and the
N355 at 16 GB, which is a validation limit rather than a controller ceiling, and
the only thing backing the seller's claim was a written message on the Amazon
thread. Confirmed three ways on arrival: the BIOS, Windows before it was wiped,
and `free -h` showing `31Gi` - 32 GiB less what the firmware and iGPU reserve.
One SODIMM slot, single channel, no upgrade path.

**There is no second NVMe slot.** The board's other M.2 is E-key and holds the
WiFi card, which is now confirmed by the card being present and working rather
than taken on the seller's word. Storage growth here is external, or the NAS.

**There may be a SATA header, and it is now curiosity rather than diligence** -
the return window has closed and the box is being kept. `Chipset → PCH-IO Configuration → SATA
Configuration` shows the controller `Enabled` in `AHCI` mode with `Serial ATA
Port 0` and `Port 1` both present and `Empty`. That is not proof: AMI enumerates
the PCH's ports whether or not the board routes them to a connector. The lid has
not been off. If a header is in there, a 2.5" SSD is the cheap expansion path the
E-key finding took away.

### Power supply

The brick takes interchangeable clip-on plug heads and **shipped with the
European head only**. XinsPower sells heads for `CN, US, JP, KR, UR, UK` but only
B2B, with no part number a consumer can order, so there is no clean way to buy
the missing one.

Input is 100-240 V, so this is a plug-shape problem and not an electrical one.
The interim answer is a bulky round travel adapter. The real answer is the cable
box rebuild in [future-plans.md](future-plans.md): the brick lives inside the box
and a one-foot pigtail carries a slim plug out to the UPS, at which point the
head shape stops mattering.

60 W is the supply's rating, not the draw. An N305 box of this class realistically
idles near 10-15 W and peaks near 35-40 W. Use the second number for UPS runtime
maths, not the first.

Do not cut the Europlug off and splice on a Mexican one. It is a mains joint on an
always-on machine inside a closed box.

### Disk baseline, recorded on install day

```
Power On Hours:      29
Percentage Used:     0%
Data Units Written:  3,203,551 [1.64 TB]
```

**1.64 TB written with 29 hours on the clock looks alarming and isn't.** That is
roughly 1.6 full passes over the drive, which is what a factory surface-validation
write test looks like. The hours are what rule out the other explanation: a disk
pulled from someone's desktop would show hundreds or thousands of hours, not 29.
Against a TLC endurance rating measured in hundreds of TB, 1.64 TB is well under
1% of rated life, so `Percentage Used: 0%` is accurate rather than evasive.

Recorded because the useful thing about these numbers is their slope. Once Immich
and Jellyfin are writing thumbnails and databases, compare against this.

**It is a budget drive and it is a single point of failure.** One M.2 socket, no
confirmed SATA, so when it dies the box is down until a replacement arrives. That
is an argument for the October offsite backup, not for a different drive.

## OS

Debian 13.7 (trixie), kernel `6.12.107+deb13-amd64`, installed 2026-09-20 from a
netinst USB in UEFI mode. No desktop. `SSH server` and `standard system utilities`
only.

Disk layout is ESP, one ext4 root, and swap. **No LVM and no encryption**, both
deliberate. LVM's flexibility has nothing to act on once bulk storage moves to the
NAS, and full-disk encryption would defeat the entire point of unattended power-on
after an outage - the box would come back from a blackout and sit at a passphrase
prompt in an empty room.

**The installer sized swap to match RAM: 31 GiB.** That is hibernation sizing on a
machine with 32 GB that will essentially never swap. Harmless at 3% of the disk,
but it has quietly eaten most of the 50 GB that [future-plans.md](future-plans.md)
budgeted for "Linux and Docker images". Not worth repartitioning; worth knowing
when the space budget gets checked.

Service state goes in `/srv/<service>`, not in per-service partitions. Same split
navi uses and for the same reason: separation by path gives you the clarity and
the backup boundaries without fixed-size guesses that will be wrong in a year.

## BIOS

Three settings were changed from shipped defaults. All three matter for a headless
box.

| Setting | Where | Was | Now |
|---|---|---|---|
| Restore AC Power Loss by IO | `Advanced → IT8613 Super IO Configuration` | Power Off | **Power On** |
| Setup Prompt Timeout | `Boot` | 1 | 3 |
| Quiet Boot | `Boot` | Enabled | Disabled |

**The AC power loss setting shipped wrong and it is not where you would look for
it.** On Intel platforms this is normally `Chipset → PCH-IO Configuration → State
After G3`; this board doesn't expose that at all, and implements it in the ITE
Super I/O menu instead. Left alone, hyrule-castle would have survived every
blackout by staying dark until somebody noticed the music had stopped.

Verified rather than assumed: mains pulled, ten seconds, plugged back in, and it
booted on its own.

`Setup Prompt Timeout` at 1 second is unpleasant now and worse later, crouched
next to a headless box with a borrowed monitor. `Quiet Boot` off means POST
messages are visible - the only times anyone looks at that screen are times
something is wrong, and a vendor logo says nothing.

Already correct and left alone: `Boot mode select: UEFI`, and `Boot Option #1:
USB Device`, which is why the install needed no boot menu.

## Network

| Interface | MAC | Address | Role |
|---|---|---|---|
| `enp3s0` | `a8:b8:e0:08:4e:f5` | `10.100.100.50` | wired, preferred |
| `enp4s0` | `a8:b8:e0:08:4e:f6` | - | unused |
| `wlp2s0` | `d8:3b:bf:53:89:50` | `10.100.100.51` | recovery only |

**`enp3s0` is the jack labelled `eth0` on the chassis.** Linux stopped naming
interfaces `eth0` a decade ago, so the sticker on the case and the name in the OS
will never agree, and this table is the only thing connecting them. The `.50`
reservation is bound to that MAC: put the cable in the other jack and the box
silently gets a pool address instead.

Both reservations live on the ER605. They were created with `Export to IP-MAC
Binding` ticked, against the standing rule in [er605.md](er605.md); the resulting
bindings were deleted on 2026-09-21 and the list is now empty.

### Two interfaces on purpose

`ifupdown` with `dhcpcd`, no NetworkManager, no systemd-networkd. The wired stanza
is its own file so nothing has to edit the one holding the WiFi PSK:

```
# /etc/network/interfaces.d/wired
allow-hotplug enp3s0
iface enp3s0 inet dhcp
    metric 100
```

Route metrics are the load-bearing part. Both interfaces land on the same /24, so
without them you get two equal default routes and the kernel picks arbitrarily -
the same class of bug as an unpinned WAN measurement, one layer down. Ethernet at
100 beats WiFi's `dhcpcd`-assigned 3004 whenever the cable is live.

**WiFi is a recovery path, not a service path.** [wifi.md](wifi.md) puts wired
ahead of wireless by roughly 50x on jitter, and this box exists to stream. But
navi has no out-of-band access at all - [navi.md](navi.md) notes its recovery path
is pulling the SD card - and during this build the WiFi interface saved a trip to
the machine three separate times, including while reconfiguring the wired
interface out from under an SSH session. Keep it.

`/etc/network/interfaces` is mode 600 because the installer wrote the PSK into it
in cleartext. Leave it that way.

### Measured on the ER605 port, 2026-09-21

`enp3s0` negotiates `1000Mb/s` full duplex. Latency from the box:

| to | min | avg | max | mdev |
|---|---|---|---|---|
| ER605 `.1` | 0.528 | 0.697 | 1.156 | 0.158 ms |
| navi `.53` | 0.183 | 0.291 | 0.504 | 0.069 ms |

**navi answers faster than the router, and that is not a fault.** LAN-to-LAN
traffic crosses the ER605's switch fabric in hardware; pinging the router itself
hits its management CPU, which deprioritises ICMP. The 0.697 ms figure understates
the path rather than describing it.

Compare against [wifi.md](wifi.md)'s wired-client-on-the-Office-Deco measurement of
`1.65/3.10/31.0/3.75 ms`: the kitchen is 4.4x better on average and **27x better on
worst case and jitter** than the office fallback would have been. That is what the
power-brick fight bought.

The navi to hyrule-castle number is also the cost of the Caddy proxy hop, which
[decisions.md](decisions.md) argued about at length: 0.291 ms.

### Gigabit is the ceiling, and that is fine

The link negotiates `1000Mb/s`. The NICs are 2.5 GbE and the Deco's ports are
2.5 GbE, but **the ER605's LAN ports are gigabit**, so 1 Gb/s is the most this
topology can carry no matter which of them the cable lands in. The dual 2.5 GbE is
decorative in this house. Don't re-argue it.

The first cable tried negotiated `100Mb/s` - a working link, quietly ten times too
slow, alarming nothing. [gotchas.md](gotchas.md) has it.

## Access

SSH with key auth, via `ssh-copy-id` from the MacBook. Host key fingerprint:

```
SHA256:5nyh8274BVsnV1pl5pj65KhRMu1XhJNb1Ku5HFRCaRc
```

Worth keeping, because it is what tells you that the machine answering on `.50` is
the same one that answered on `.117` during the build rather than something else
that grabbed the address.

User is `enrique-ramirez`. A root password was set during install, which has a
consequence documented in [gotchas.md](gotchas.md): Debian then declines to
install the `sudo` package, leaving the user in a group whose command does not
exist. It was installed by hand afterwards.

Key-only, matching navi, in `/etc/ssh/sshd_config.d/99-hardening.conf` as of
2026-09-21:

```
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
```

Verified from the MacBook after the restart rather than assumed: key auth
succeeds, and both a password attempt and a root login come back
`Permission denied (publickey)`.

`ssh.service` is enabled and `ssh.socket` is disabled, so this is a classic
service - a plain `systemctl restart ssh` applies changes. Worth knowing because
Debian 13 can run sshd socket-activated, and there the restart would not.

**Recovery if ever locked out is physical.** These settings apply to every
interface, so the WiFi path does not help - it's a monitor and keyboard on the
box, with a Dvorak console. Validate with `sudo sshd -t` before restarting;
that turns the only realistic lockout cause into a caught error.

`sudo` asks for a password here. navi has it passwordless via
`/etc/sudoers.d/010_enrique-nopasswd`; this box does not, which is a small
inconsistency to settle deliberately rather than drift into.

**The one exception is the player.** `/etc/sudoers.d/020_foobar2000-restart`,
installed by `deploy.sh` from
[../hyrule-castle/sudoers/](../hyrule-castle/sudoers/), allows `systemctl
stop|start|restart foobar2000` without a password, and nothing else. It exists so
a `foo_jean` deploy can swap the component DLL over SSH without anyone typing a
password. It is scoped this narrowly on purpose, because allowing all of
`systemctl` would amount to root access. `deploy.sh` runs `visudo -c` on the file
before installing it: a broken sudoers file breaks sudo entirely, and with root
SSH disabled, fixing it means a keyboard at the box.

The console keyboard is **US Dvorak**. Set through `dpkg-reconfigure
keyboard-configuration` rather than by editing `/etc/default/keyboard`, for the
reason in [gotchas.md](gotchas.md). This only affects someone physically at the
machine, which is exactly the break-glass case - so anyone helping debug it at
3am needs to know before they touch the keys.

## Updates

`unattended-upgrades` 2.12, restricted to the Debian security pocket, configured
2026-09-21 in `/etc/apt/apt.conf.d/52unattended-upgrades-local` - a drop-in rather
than an edit to the shipped file, so a package upgrade can't quietly revert it.

Two defaults had to be overridden, and one of them is a trap:

- **The general archive is enabled by default** and needs `#clear` to remove,
  because apt.conf lists append rather than replace. [gotchas.md](gotchas.md) has
  the detail; it is not a Raspberry Pi OS quirk as previously recorded.
- **`/etc/apt/apt.conf.d/20auto-upgrades` did not exist**, so nothing periodic ran
  despite the service being enabled. Created with
  `APT::Periodic::Update-Package-Lists` and `APT::Periodic::Unattended-Upgrade`.

In force, verified rather than assumed:

```
Allowed origins are: origin=Debian,codename=trixie,label=Debian-Security,
                     origin=Debian,codename=trixie-security,label=Debian-Security
```

Automatic reboots are off, explicitly rather than by inherited default. This box
streams music and will serve video; it doesn't get to choose when it disappears.
Docker's packages are blacklisted ahead of being installed, for navi's reason:
upgrading the container engine restarts every container.

Kernel upgrades are not excluded here as they are on navi. navi's exclusion exists
because a bad kernel on a box with no monitor is a bad afternoon; hyrule-castle has
HDMI and a keyboard can reach it. Revisit if that stops being true.

## What navi knows about it

`PIHOLE_HOSTS` carries `10.100.100.50 hyrule-castle hyrule-castle.lan`, added
2026-09-21. `ocarina.lan` and `music.lan` deliberately stay pointed at navi and
are proxied onward - see [decisions.md](decisions.md).

Kuma monitor 14, a 60-second ping on `.50`, reading `<1ms`.

**A `.env` edit is not applied until the container is recreated.** `deploy.sh`
passes `--env-file` to compose, which does detect env changes - but the deploy has
to actually be run, and it reporting success is not proof. The check:

```sh
sudo docker inspect pihole --format '{{.State.StartedAt}}'
sudo docker inspect pihole --format '{{range .Config.Env}}{{println .}}{{end}}' | grep hosts
```

A recent `StartedAt` plus the expected value in that env line. This is the same
lesson `deploy.sh` already records in a comment about Caddy, generalised: the
script succeeding and the container having taken the change are different facts.

## The music library

`/srv/music/library` holds the sorted library - 349 GB, 37,091 files, copied
2026-09-21 from the old Toshiba over USB rather than over the network, which kept
filename encoding a single conversion done once by the kernel's vfat driver rather
than a chain of translations through Windows and SMB. A Spanish-language library is
full of accents; mojibake across 37,000 names is not something you want to discover
later.

`/srv/music/inbox` exists and is empty. The 79 GB of unsorted material stayed on
the Toshiba pending a Mac-side sorting workflow, and is knowingly single-copy until
that happens.

**This path does not move.** In October the 16 TB USB disk mounts at `/srv/music`
and the contents move onto it; the path stays. See
[future-plans.md](future-plans.md) for the ordering, which never drops below two
copies.

### The layout foobar2000 needs

Not a drive letter. foobar2000's library index holds `file-relative://` paths, so
what matters is that `Musica` is a **sibling of the install directory**:

```
/srv/fb2k/foobar2000/                     the portable install
/srv/fb2k/Musica -> /srv/music/library    symlink
```

The symlink is what decouples the two. October's remount changes the contents of
`/srv/music/library` and the symlink keeps pointing at it, so nothing in
foobar2000's config ever learns the disk changed. Keep the install out of
`/srv/music` itself or it vanishes with that mount.

## The music player

foobar2000 **v2.25.10 x64**, portable, at `/srv/fb2k/foobar2000`, running headless
under Wine 10.0 and Xvfb as a systemd service. Migrated 2026-09-22.

```
/srv/fb2k/
├── foobar2000/            the portable install, including profile/
└── Musica -> /srv/music/library

~/fb2k-wine/               the Wine prefix, win64
└── dosdevices/f: -> /srv/fb2k
```

So `F:\foobar2000\` and `F:\Musica\`, and the library's `file-relative://..\Musica\`
paths resolve. **The prefix deliberately lives outside `/srv/fb2k`.** It was inside
at first, which made `F:\wine\dosdevices\f:` point back at `F:` - a loop any
library scan of the drive root would have followed forever. It is also disposable
in a way the profile is not: a broken prefix should be deletable in thirty seconds
without threatening the library index.

**The drive letter is cosmetic.** Every path in the index is relative, so `F` was
chosen only because it matches what the Windows machine used.

### What came across, and what did not

Fresh binaries and components, old profile. The three components were installed on
Windows, where a GUI exists, rather than driving an installer under Xvfb:
`foo_audioscrobbler`, `foo_enhanced_playcount`, `foo_openlyrics`. Deliberately not
carried over: `foo_beefweb` and `foo_jean`, because the migration off beefweb is
still in progress and one change at a time is the point. Also dropped, and worth
knowing in case they are missed: `foo_quicksearch` and `foo_quicktag`, which were
installed on the old machine. Their settings came across, so installing them later
picks up where they left off.

Transplanted from the old profile: `metadb.sqlite`, `config.sqlite`, `library-v2.0`,
`playlists-v2.0`, `configuration/`, `dsp-presets/`, `config.fb2k-dsp`, `theme.fth`.

**`metadb.sqlite` is the irreplaceable one.** 91.6 MB holding 30,446 tracks, and -
this is the part that is not obvious - every play count. foobar2000's own
`playCount` and `rating` columns are empty; `foo_enhanced_playcount` keeps its data
in GUID-named `metadb_index_*` tables inside the same file. The fresh install
created the same index GUIDs because it has the same components, so the old data
landed exactly where the new components look for it.

Verified after landing: `PRAGMA integrity_check` ok on both databases, 30,429
tracks in the library, every playlist present, Last.fm credentials intact.

### Output is Null Output, and has to be

The box has no sound card and Wine's audio driver is disabled outright:

```sh
wine reg add "HKCU\Software\Wine\Drivers" /v Audio /d "" /f
```

Without that, foobar2000 can stall on a modal audio-init error nobody can see.
Audio reaches listeners through `foo_jean`'s stream endpoint rather than the
machine's own playback, so this is the correct permanent setting rather than a
workaround.

### Sixteen files do not play

`profile/library-error-log.txt` lists them, and **it appends one copy per
startup** - 52 lines after three starts is still the same 16 files.

| count | format | why |
|---|---|---|
| 11 | `.wma` | Sidilarsen, *(2005) Eau* - Windows Media codecs are not in Wine |
| 1 | `.wmv` | a Professor Elemental video, same reason |
| 4 | `.mp3` | Masashi Hamauzu - "Unsupported format or corrupted file" |

The Sidilarsen album is **entirely** unplayable here, 11 of 11 tracks. Re-acquiring
it in a sane format is the fix; there is no codec to install.

30,446 in the index minus these 16, minus the 4 test files under
`..\foo_jean-test\` that were not copied, gives the 30,429 the player reports.

### The foo_jean test tree

```
/srv/fb2k/foo_jean-test/     F:\foo_jean-test\
├── one/                     library folder
├── two/                     library folder
└── loose/                   deliberately NOT a library folder
```

`foo_jean`'s tag-write tests write ratings and tags into real files. **They must
never touch `/srv/music`.** This tree gives them their own copies. `deploy.sh`
creates the empty folders. `foo_jean`'s `test-fixtures` script fills them, and
refilling them is its job, not this repo's. `one` and `two` hold different
recordings at the same relative path. `loose` sits outside the library on
purpose. The script's header explains why both matter.

Registering `one` and `two` as library folders is a one-off step in the GUI:
Preferences → Media Library, over the VNC tunnel below. That setting lives in
`config.sqlite`, so it is covered by the backup. After a rebuild from a fresh
profile, it has to be done again.

The tree is disposable and is not backed up.

### Stopping it correctly is not obvious

The unit runs two `ExecStop` commands and both are load-bearing:

```
ExecStop=/usr/bin/wine .../foobar2000.exe /exit
ExecStop=/usr/bin/wineserver -w
```

`/exit` is a Windows shutdown request. A bare SIGTERM to the Wine process is not,
and without it foobar2000 never flushes `metadb.sqlite` - every play count since
the last flush would be lost on each restart. Confirmed working: a clean stop
writes `profile/nobadshutdown` and `metadb.sqlite` grows.

`wineserver -w` exists because the player exits and the **launcher does not** -
wineserver lingers while the session winds down, systemd waits out
`TimeoutStopSec`, and a perfectly clean shutdown gets marked `failed`. It waits
rather than kills on purpose: `wineserver -k` is the obvious fix and it is wrong,
because it races the metadb flush `/exit` just started. That flush was measured at
about seven seconds.

**Both of those only work if the `ExecStop` commands reach the same wineserver
the player is using.** For a while they did not, and every stop took two minutes
and ended as `Result=timeout`. The cause was the place Wine 10 keeps its socket.
It uses `/run/user/1000/wine/` if `/run/user/1000` exists, and
`/tmp/.wine-1000/` if it does not. `XDG_RUNTIME_DIR` makes no difference. Without
linger, logind creates `/run/user/1000` when you log in and deletes it when your
last session ends. So:

- If the player was started over SSH, its socket was deleted when that SSH
  session ended.
- If the player was started at boot, its socket is in `/tmp`, but the next time
  anyone logs in, Wine looks in `/run/user/1000` first.

In either case `wine foobar2000.exe /exit` found no server, so it started a
**second** Wine session. `wineserver -w` then waited on the wrong server. When
systemd sent SIGTERM to what was left, one `winedevice.exe` from the original
session ignored it and held the unit in `final-sigterm` until the timeout.
Observed on 2026-09-24: two `wineserver64` processes, two `services.exe`
processes, and so on, all in the one cgroup.

The fix is `loginctl enable-linger enrique-ramirez`, which `deploy.sh` runs.
With linger on, `/run/user/1000` exists from boot to shutdown whether anyone is
logged in or not. The unit is ordered after `user-runtime-dir@1000.service` so
the directory is there before Wine goes looking for it.

### Seeing the GUI

Xvfb is a real X server with no monitor, so the GUI is available whenever wanted:

```sh
ssh -t -L 5900:localhost:5900 enrique-ramirez@10.100.100.50 \
    'x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -passwd <throwaway>'
```

Then `vnc://localhost:5900` from the Mac. Bound to localhost and tunnelled, so
nothing is exposed on the LAN - which is what makes a throwaway password
acceptable. On demand only, never as a service.

`openbox` runs as a unit alongside Xvfb. Without a window manager nothing on `:99`
can be moved or resized, and modal dialogs land wherever they land - which makes
Preferences unusable. The first launch proved the point: foobar2000 restored a
window position from the Windows machine that put it at `X=1210` on a 1280-wide
screen, leaving 70 visible pixels and no way to drag it.

## What is in git, and what is not

Config is in the repo at [../hyrule-castle/](../hyrule-castle/) - units, a deploy
script, and the profile backup. A few KB, no secrets. Applied the same way navi
is, by a human:

```sh
cd /srv/navi && git pull && sudo ./hyrule-castle/scripts/deploy.sh
```

Everything foobar2000 accumulates stays out: the 25 MB install, the Wine prefix,
`library-v2.0`, and both SQLite databases - `config.sqlite` because it holds the
Last.fm session, `metadb.sqlite` because it is 92 MB rewritten constantly.

**`fb2k-backup.timer` exists because of that exclusion.** `metadb.sqlite` holds
every play count and would otherwise be protected by nothing at all. Daily, keeps
fifteen, mode 600. It copies both databases through SQLite's online backup API
rather than `cp`: foobar2000 holds them open and writes while running, and a plain
copy of a live database can be internally inconsistent in a way that surfaces
later as missing play counts rather than as an error.

Backups are local only, in `/srv/backup`. Same gap navi has - both copies in one
flat - and the offsite plan in [future-plans.md](future-plans.md) is what closes
it.

## Where it lives

The kitchen, wired directly into the ER605's fifth LAN port, which
[network.md](network.md) has been holding for it. Same reasoning that keeps navi
off a Deco: one less device in the path, one less thing whose reboot takes the
services offline.

It very nearly ended up in the office on the office Deco instead, because the
power brick wouldn't fit the kitchen cable box. That would have cost the UPS, put
a 7200 RPM drive in a room somebody works in, and added a wireless backhaul hop to
every request. The pigtail rebuild in [future-plans.md](future-plans.md) is what
made the kitchen work - the bricks go in the box, slim plugs come out.

**It powers on by itself when mains is applied.** There is no button to press at
the far end, by design.

## Not done yet

In rough order:

- Replace the ping monitor with something that proves the stream works, once
  there is a stream
- `foo_jean`, once the migration off beefweb finishes. Then `MUSIC_BACKEND` in
  navi's `.env` moves to `10.100.100.50:8881`. The Caddyfile is already
  written for it: one vhost, with no `:8881` listener and no `/jean/` prefix.
  The sudo rule
  and the test tree it needs are already in place. Registering `one` and `two`
  as library folders is the only step left, and it is manual. See *The foo_jean
  test tree*
- WMA playback, if it proves worth it. Eleven tracks of one album; re-acquiring it
  in another format is probably cheaper than making Wine decode Windows Media
- Offsite backup, covering `/srv/backup` as well as the library
- `wine` and `xvfb` from Debian, a systemd unit for foobar2000, then the library
  migration. 64-bit only - see [future-plans.md](future-plans.md)
- Docker CE, **at the Jellyfin phase and not before** - see
  [decisions.md](decisions.md)
- Open the lid and settle the SATA question while the return window allows
