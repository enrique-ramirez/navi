# Things that cost hours

Each of these looked like a different problem than it was.

## `custom.toml` doesn't exist on Trixie images

The Imager-style `custom.toml` first-boot config is a Bookworm-era mechanism.
Grep the Trixie Lite image and it appears zero times, against 46 hits for
`firstboot` and 3 for `userconf.txt`.

A Pi given `custom.toml` boots into a perfectly working system with no user
account and no SSH. It pings fine and refuses port 22, which reads like a network
fault and isn't one.

Use an empty `ssh` file plus `userconf.txt` containing `username:hash` from
`openssl passwd -5`. The username has to match `^[a-z][a-z0-9-]*$`.

Verify the mechanism against the image you actually downloaded rather than a blog
post. It takes thirty seconds:

```sh
grep -a -c custom.toml 2026-06-18-raspios-trixie-arm64-lite.img
```

## Apply EEPROM config after apt, never before

Staging `BOOT_ORDER` and then running `apt full-upgrade` silently discards it. The
`rpi-eeprom` package upgrade re-stages the bootloader image with its default
config, and the next reboot applies that instead.

It fails quietly. `rpi-eeprom-config` afterwards simply shows no `BOOT_ORDER`
line. Always re-read the config after the reboot that was supposed to apply it.

## ER605 policy routing is TCP only

This is the big one, and it invalidates the obvious design.

Two source aliases were pinned to a WAN each by policy route, then egress was
measured per protocol:

| Probe | `.61` | `.62` | Honoured? |
|---|---|---|---|
| HTTPS via `curl --interface`, 6 runs | Telmex | Megacable | yes, 6/6 |
| DNS via `dig -b @8.8.8.8` | Megacable | Megacable | no |
| `traceroute -I` | Megacable | Megacable | no |

The rule says Service Type ALL. It isn't. UDP and ICMP fall back to load
balancing.

So a `ping -I <source>` per-WAN monitor would sit green while measuring whichever
line the router picked. Green, meaningless, and indistinguishable from working,
which is the exact failure this box exists to eliminate.

## Cloudflare's ping time is a lie

The old notes said Megacable routes to Cloudflare badly, measured at 55 ms against
11 ms to Google. That's an ICMP measurement, and Cloudflare deprioritises ICMP.

By DNS query time, which is the thing that actually matters for a resolver:

```
1.1.1.1          Cloudflare       9 ms
1.0.0.1          Cloudflare      11 ms
149.112.112.112  Quad9           12 ms
8.8.8.8          Google          14 ms
208.67.222.222   OpenDNS         49 ms
```

Cloudflare is the fastest resolver here by a clear margin. The Kuma ping monitor
later showed the same address at 10.2 ms after the load balancer reshuffled, so
even the ping number wasn't stable. Don't pick resolvers by ping.

**Update 2026-09-07: the old note was right and the reasoning here was wrong.**
TCP traceroute per line puts Megacable at 46.7 ms to `1.1.1.1` against Telmex's
9.3 ms - which is the 55-versus-11 split the old notes described, near enough.
Cloudflare does deprioritise ICMP; that true fact was deployed as a wrong
explanation. The two measurements disagreed because they left by different WANs,
and the load balancer decides that, not you.

The conclusion survives, Cloudflare is still the right resolver, but the lesson
generalises well past resolvers: **any unpinned measurement of "the internet"
from this network measures whichever line the load balancer happened to pick.**
Pin the source to `.61` or `.62` and use TCP, or don't quote the number.

## Two ways to misread whether a domain is blocked

Both were made during the HaGeZi switch, in opposite directions, and both produced
confident wrong conclusions.

An empty DNS answer is not a block. It usually means NXDOMAIN or no A record.
Testing that way falsely reported Apple push and Samsung as broken.

An exact-match lookup in the `gravity` table is not authoritative either. ABP
entries are wildcards: `||g.doubleclick.net^` blocks every subdomain without those
subdomains existing as rows. `securepubads.g.doubleclick.net` returns zero rows
and is definitely blocked.

Only the `dig` answer counts. `0.0.0.0` means blocked, anything else doesn't.

## Monitor canaries need to survive list changes

The blocking check originally used `doubleclick.net` as its canary. HaGeZi doesn't
block that apex, only its ad-serving subdomains, so switching blocklists made a
perfectly healthy Pi-hole report NOT BLOCKING.

It now checks two canaries and only alarms if both resolve. Any monitor that
hardcodes an assumption about the thing it watches will eventually cry wolf when
that thing legitimately changes, and a monitor you've learned to disbelieve is
worse than none.

## unattended-upgrades is wider than you think, on Debian itself

The default `Origins-Pattern` in `/etc/apt/apt.conf.d/50unattended-upgrades`
includes `origin=Debian,codename=${distro_codename},label=Debian` - the general
archive, not just security - **uncommented and active**. Left alone it
auto-applies every stable update.

This was first found on navi and written down as a Raspberry Pi OS quirk. It
isn't. A stock Debian 13 netinst with `unattended-upgrades` 2.12 ships the same
active line, confirmed on hyrule-castle 2026-09-21. Assume it on every Debian
box you build, and check rather than assuming it's been fixed upstream.

**Overriding it needs `#clear`, because apt.conf lists append.** Redeclaring
`Unattended-Upgrade::Origins-Pattern` in a higher-numbered drop-in adds to the
existing list rather than replacing it, so the general-archive entry survives and
nothing looks wrong. The working form:

```
#clear Unattended-Upgrade::Origins-Pattern;
Unattended-Upgrade::Origins-Pattern {
        "origin=Debian,codename=${distro_codename},label=Debian-Security";
        "origin=Debian,codename=${distro_codename}-security,label=Debian-Security";
};
```

Verify, don't assume - this prints the list actually in force:

```sh
sudo unattended-upgrade --dry-run --debug 2>&1 | grep -i 'allowed origins'
```

**Installing the package does not switch it on.** `unattended-upgrades.service`
gets enabled, which is misleading: the periodic run is driven by
`apt-daily-upgrade.timer`, which checks `APT::Periodic::Unattended-Upgrade` and
does nothing unless it's set. A minimal Debian install ships no
`/etc/apt/apt.conf.d/20auto-upgrades` at all, so the package sits installed and
inert with every timer enabled and green.

## The green LED is not a liveness light

`ACT` shows SD card activity. On a booted, idle Pi it's completely dark. Reading
"no green LED" as "it never booted" sends you chasing router config for an hour.

The ethernet lights mislead too: the Pi 4's bootloader brings up the PHY before
any OS exists, so they'll light on a Pi with no card in it at all.

## First boot takes minutes, not one

It resizes the root partition and reboots itself. Scanning for it too early finds
nothing, and that absence isn't evidence of anything.

You can confirm the resize happened by comparing partition sizes. The image ships
a 2.43 GB root partition; a booted card shows the full card size.

## The ER605 checks Referer against Host

Its web server 404s every `.js` and `.css` unless the request carries a `Referer`
whose host matches the `Host` header. It doesn't care what that host is, only that
they agree:

| Host | Referer | Result |
|---|---|---|
| `10.100.100.1` | `10.100.100.1` | 200 |
| `router.lan` | `router.lan` | 200 |
| `10.100.100.1` | `router.lan` | **404** |
| `router.lan` | `10.100.100.1` | **404** |

So when proxying it, **don't rewrite the Host header.** Setting
`header_up Host {upstream_hostport}` seems like the careful thing to do for an
appliance and is exactly what breaks it: the browser keeps sending
`Referer: router.lan`, the mismatch 404s every asset, the app falls through to
`error.html`, and you get a blank page with sixty 404s in the network tab.

Testing this with `curl` is misleading, because a bare `curl` sends no Referer and
gets 404s whether it goes direct or through the proxy. That looks like the proxy
being faithful when it's actually both paths failing for the same unrelated
reason.

## Two ER605 UI quirks

System Status shows only WAN interfaces. There's no LAN port status on that page,
so "nothing appears for the port I plugged into" is expected and means nothing.
Use Network → LAN → DHCP Client List.

Address Reservation sometimes rejects a valid IP with "The IP address is not in
the same subnet as the IP address of LAN port." It's a stale client-side
validator, usually triggered by browser autofill. Hard-refresh and type the
address by hand.

## Browsers cache DNS failures

After flipping DHCP to Pi-hole, a browser can keep failing on `.lan` names for a
while even though the system resolves them fine. Check at the system level first:

```sh
curl http://help.lan
ipconfig getpacket en0 | grep domain_name_server   # macOS
```

Browsers with DNS-over-HTTPS enabled bypass Pi-hole entirely and will never
resolve `.lan`. If one browser works and another doesn't, that's the reason.

## Encode push message parameters properly

Uptime Kuma push URLs carry the message as a query parameter. A hand-rolled
"replace spaces with %20" breaks the moment a message contains `%` or `&`, which
happened the first time the disk usage was included. `curl -G --data-urlencode`
does it correctly.

## Background processes die when the last SSH session closes

`nohup cmd &` over SSH is not enough. `Linger=no` is the default, so when the last
session for a user ends, systemd stops `user@UID.service` and tears down the user
slice, taking everything in it. `KillUserProcesses=no` does not prevent this - it
is a different mechanism, and checking it will mislead you.

The symptom is confusing because it is intermittent: a job survives for as long as
you keep poking at the box, then dies during a gap. Xvfb and Wine both vanished
this way while a `flac` scan started the same way survived, purely because it was
being polled every few minutes.

Anything meant to outlive a session needs a **systemd unit**, or
`loginctl enable-linger <user>` - which itself needs root.

Related: **Ctrl-C does not kill a remote command.** `ssh host 'cmd'` allocates no
TTY, so SIGINT reaches the local client and not the remote process. An x11vnc left
running this way held port 5900 and caused a completely unrelated-looking failure
twenty minutes later. Use `ssh -t` when you will want to interrupt it.

## Restarting Xvfb kills everything drawing on it

Obvious in hindsight, not at the time: X clients die when their X server goes
away. `systemctl restart xvfb.service` therefore terminates foobar2000
*abnormally*, whatever the dependency graph says, because the display is pulled
out from under it before its own shutdown can run.

Stop the clients first, cleanly, then the server:

```sh
sudo systemctl stop foobar2000
sudo systemctl restart xvfb
sudo systemctl start openbox
sudo systemctl start foobar2000
```

## A GUI app as a headless service can hang on a dialog nobody sees

After one abnormal termination, foobar2000 starts with *"foobar2000 was terminated
abnormally last time"* and waits for a click. On a desktop that is helpful. As a
service it is a hang: systemd reports `active`, the process is alive, and it is
doing nothing at all, with no error anywhere.

Tick **"Do not show this dialog again - start normally each time"** the first time
you see it, over VNC.

The cause was self-inflicted: the profile transplant excluded `nobadshutdown` as
noise. It is not noise - it is foobar2000's clean-shutdown marker, and its absence
is exactly what triggers that dialog.

## The wine launcher outlives the app it launched

`wine app.exe /exit` returns 0, the app shuts down properly, and the `wine` process
systemd is watching stays alive - wineserver lingers while the session winds down.
systemd waits out `TimeoutStopSec` and marks a clean shutdown `Result=timeout`, so
the unit shows `failed` after every normal stop.

```
ExecStop=/usr/bin/wine .../app.exe /exit
ExecStop=/usr/bin/wineserver -w
```

`-w` waits for wineserver to exit. **Do not use `-k`.** It is the obvious fix and
it races whatever flush `/exit` just started - about seven seconds for
foobar2000's metadb, which is where every play count lives.

## `MemoryCurrent` on a file-reading service is not a memory figure

`systemctl show -p MemoryCurrent` reported foobar2000 climbing about 1 GB every
five seconds. It looked exactly like a runaway leak and was not: cgroup v2 charges
**page cache** to the cgroup, so every library file it touched counted.

```
memory.current  6,483 MB
  anon            390 MB   <- the real figure, flat
  file          6,070 MB   <- reclaimable page cache
```

Read `anon` in `memory.stat`, or sum RSS across the cgroup's processes. Page cache
is returned the moment anything else wants it.

## `pgrep -f` matches the command asking the question

`pgrep -f flacscan.py` inside `bash -c 'while pgrep -f flacscan.py ...'` matches
the wait loop's own command line. The loop watched itself and never exited; every
status check it fed back said the scan was still running for ten minutes after it
had finished.

Hit three separate times in one evening, including in the command written to
*verify* a kill had worked. Use `pgrep -x <name>` to match the process name, or
check `/proc/<pid>` directly. Never build a wait loop on a `-f` pattern that
appears in its own arguments.

## x11vnc silently moves to another port

With 5900 busy, x11vnc **autoprobes** and takes 5901, announcing it in one line
buried in sixty lines of startup output. An SSH tunnel pointed at 5900 then
reaches whatever else is there, and the VNC client hangs on `Connecting...` with no
useful error.

Pass `-rfbport 5900` so it either gets that port or fails loudly.

Separately: **macOS Screen Sharing will not connect to a `-nopw` server.** x11vnc
offers the `None` security type and Apple's client demands a password anyway, then
hangs. Give it `-passwd <anything>` - over an SSH tunnel bound to localhost the
password is theatre, but the client needs it.

## `flac -t` blames ID3 for damage ID3 did not cause

A FLAC with an ID3v1 tag appended fails `flac -t` with `LOST_SYNC ... state =
FLAC__STREAM_DECODER_END_OF_STREAM`, and flac helpfully notes that the ID3v1 tag
"is probably the cause". **Probably.** Across 558 flagged files it was right 519
times and wrong 39 times, and the 39 were the ones that mattered - genuinely
truncated files whose real fault the note masked.

The two look identical in flac's output. What separates them is whether the
stream contains as many samples as its own header claims:

```sh
metaflac --show-total-samples file.flac     # what the header declares
flac -t file.flac 2>&1 | grep "after processing"   # what actually decoded
```

Equal means the audio is whole and the ID3 trailer is the only problem. Fewer
decoded than declared means the file is short and no amount of tag-stripping will
fix it.

Two traps found while working this out. `metaflac --show-md5sum` only **reads**
the MD5 out of STREAMINFO - it verifies nothing, so an unchanged value proves only
that the header was not rewritten. Only `flac -t` decodes and compares. And
testing a fix on one album picked at random is how you conclude it does not work:
the album chosen first was one of the five truncated ones, out of 53.

## A silent `rsync --dry-run -c` is the success case

The checksum verification pass prints only *differences*. Redirect it to a file
and the terminal shows nothing at all for over an hour, which reads exactly like a
hung process. It isn't.

There is no progress output either, because `--info=progress2` would go to the
same redirect. To watch it, read what the process has actually pulled off disk:

```sh
awk '/read_bytes/{printf "%.1f%%\n", $2/374e9*100}' \
    /proc/$(pgrep -f 'rsync -rltc'|head -1)/io
```

An empty output file at the end is the pass. `grep -c '^>' /tmp/verify.txt`
returning `0` says so explicitly.

## New Debian boxes reject `xterm-ghostty`

`tmux` on a freshly built box dies with `missing or unsuitable terminal:
xterm-ghostty`. It looks like a tmux problem and is a terminfo one - Debian's
`ncurses-base` has no entry for Ghostty, and nothing on the remote will ever
grow one on its own.

Unblock with `TERM=xterm-256color tmux new -s work`. Fix it properly, once per
box, **from the Ghostty window itself** and not from inside an SSH session:

```sh
infocmp -x | ssh user@host -- tic -x -
```

That compiles the local entry into `~/.terminfo` on the remote. Run from a shell
with no `TERM` set - an agent, a script, a CI job - `infocmp` has nothing to
export and the command silently installs nothing while appearing to succeed.

Expect this on every box built from here: `tatl`, the NAS, anything else.

## AC power loss recovery is in the Super I/O menu, and it ships wrong

On Intel platforms this setting is normally `Chipset → PCH-IO Configuration →
State After G3`. hyrule-castle's AMI Aptio build doesn't expose it there at all -
that submenu contains only PCI Express, SATA, USB and HD Audio. It lives in
`Advanced → IT8613 Super IO Configuration → Restore AC Power Loss by IO`.

It shipped set to power **off**. An always-on headless box that stays dark after
a blackout produces no symptom except the services being gone, which is the same
silent failure this whole project exists to delete.

Prefer `Power On` over `Last State`. Last State only brings the machine back if it
happened to be running when power died, and "almost always" is not a property you
want in an unattended recovery path.

Verify it rather than trusting the menu: pull the cord, wait ten seconds, plug it
back in, don't touch the button.

## A working ethernet link can be ten times too slow

hyrule-castle's first cable came up perfectly - `LOWER_UP`, `Link detected: yes`,
carrying traffic - at `100Mb/s`. A second cable on the same port and the same Deco
negotiated `1000Mb/s`.

100BASE-TX needs two pairs and gigabit needs four, so a Cat5 cable, a two-pair
patch lead, or one damaged pair produces a link that works and alarms nothing. The
only way to see it is to look:

```sh
sudo ethtool enp3s0 | grep -E 'Speed|Link detected'
```

`Link partner advertised link modes` is the diagnostic when it is slow. If the
switch is offering 1000 and you negotiated 100, the cable is dropping pairs. If
the partner itself only offers 100, something 100 Mbit is in the path.

**`ethtool` omits every `Link partner...` line when there is no link at all.** A
`sed` range or a `grep` anchored on one of them prints nothing, which reads as a
broken command rather than as the answer. Use `ip -br link` and look for
`LOWER_UP` to distinguish "no link" from "slow link".

## The chassis says `eth0`, the kernel doesn't

hyrule-castle's case is labelled `eth0` and `eth1`. Linux has used predictable
names derived from PCI topology for about a decade, so those stickers match
nothing. `enp3s0` is the jack labelled `eth0`.

That mapping is the only thing tying the physical port to the DHCP reservation. Put
the cable in the wrong jack and the box comes up on a pool address with nothing
explaining why. The table in [hyrule-castle.md](hyrule-castle.md) is the record;
the port also has a physical label now.

## Setting a root password means you get no `sudo` command

Debian's installer grants the first user `sudo` **only if you leave the root
password blank**. Set one, and it doesn't.

The confusing part is that `groups` still lists `sudo`, because the group ships in
`/etc/group` on every Debian system regardless. So the user is in a group granting
rights to a binary that was never installed, and every command fails with
`sudo: command not found` rather than anything about permissions.

Fix from a root shell: `apt install sudo`, then `usermod -aG sudo <user>` if the
installer didn't add them.

## `/etc/default/keyboard` doesn't own itself

Editing that file by hand appears to work and then doesn't survive. It's managed
by `keyboard-configuration` through debconf, and the console keymap is generated
from it into a cache under `/etc/console-setup/`. A hand edit leaves debconf
holding the old answers and the cache built from them, so `console-setup` applies
the stale version at boot - and the next package update overwrites your edit
anyway.

Use `sudo dpkg-reconfigure keyboard-configuration`. It works fine over SSH,
because it's a debconf dialog. The variant - Dvorak, in this case - is on a
*second* screen after you pick the country, which is the step that gets missed.

`setupcon` will refuse to do anything over SSH, reporting `We are not on the
console`. That's correct behaviour, not a failure; the config applies at next boot
regardless.

## Pasting a block whose first command reads stdin

`sudo apt install -y ethtool` followed by eight more pasted lines runs the install
and silently swallows everything after it. `apt` consumes the queued input as its
own, the commands never execute, and the prompt comes back clean - so it looks
like they ran and produced nothing.

Paste `apt` on its own. Same for anything else that reads stdin, and run `sudo -v`
on its own line first so a password prompt can't eat the block either.

## macOS raw disk writes need Full Disk Access, and `sudo` doesn't help

`dd` to `/dev/rdiskN` fails with `Operation not permitted` unless the *calling
application* holds Full Disk Access. TCC attaches the grant to the app, not the
user, so `sudo` does not get you around it - and the app is whatever terminal
you're in, which may be a code editor rather than Terminal.app.

`diskutil unmountDisk` also fails on a busy volume and leaves the raw device
locked, producing the same error for a different reason. Use `unmountDisk force`.

Easiest route is to skip `dd` and use Raspberry Pi Imager's **Use custom** option,
which handles both the unmount and the authorisation through its own privileged
helper.

## The ER605 gives reserved addresses an infinite lease

Pool clients get the 120 minutes in [network.md](network.md). A reserved address
comes back as `leased ... for infinity`, so the client never renews.

Consequence: editing a reservation does nothing visible until the client is
rebooted or bounced with `ifdown`/`ifup`. Twenty minutes of re-checking the router
UI is the usual way to discover this.

## `Export to IP-MAC Binding` is inert until suddenly it isn't

The Address Reservation form offers it, defaults to ticked, and is harmless on its
own - just a row in a table nothing reads. Which is exactly why it gets left on.

It becomes load-bearing the moment anything ticks **"Permit the packets matching
the IP-MAC Binding entries only"** under Firewall → Anti-ARP Spoofing. At that
point every device in the flat without a binding loses the network: TVs, consoles,
phones, and the WiFi side of any machine bound only by its wired MAC. A security
setting that takes the house offline is a bad twenty minutes.

[er605.md](er605.md) therefore says leave it unchecked on every reservation, which
is the right call: it deletes the trap rather than depending on nobody ever
enabling strict mode years from now.

**The worse part is that you cannot undo it where you did it.** The checkbox exists
only on the Address Reservation *Add* form. Reopen that reservation to edit it and
the field is simply absent - MAC, IP, Description and Status, nothing else. What
the tick did was write a row into a different table entirely, and the row outlives
any amount of staring at the reservation screen.

To remove it: **Firewall → Anti ARP Spoofing → IP-MAC Binding List**, select, delete.
Deleting there does not affect the DHCP reservation; they are separate tables.

Worth checking that list even if you believe you never ticked the box. When it was
first opened on 2026-09-21 it held an entry for the main Deco that nobody
remembered creating, and which this repo had been asserting did not exist.
