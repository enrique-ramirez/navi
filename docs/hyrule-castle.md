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

**There may be a SATA header.** `Chipset → PCH-IO Configuration → SATA
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
- Docker CE from Docker's own repo, pinned key, same as navi
- foobar2000 under Wine and Xvfb, then the library migration
- Open the lid and settle the SATA question while the return window allows
