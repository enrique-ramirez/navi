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

## unattended-upgrades is wider than you think

Raspberry Pi OS's default origins include `origin=Debian,codename=trixie,label=Debian`,
the general archive, not just security. Left alone it auto-applies all stable
updates.

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
enabling strict mode years from now. hyrule-castle's two entries were created with
it ticked on 2026-09-20 and want undoing.
