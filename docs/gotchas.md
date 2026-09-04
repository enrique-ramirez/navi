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
