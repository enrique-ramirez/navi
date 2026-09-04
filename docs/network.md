# The house network

## Shape of it

Two ISPs land in the kitchen. Both terminate on a TP-Link ER605, which does the
routing and load balancing. Wi-Fi is three Deco XE75 Pro units in access point
mode, so the Decos are dumb radios and the ER605 makes every decision.

```
Telmex 500/500 ──┐
                 ├── ER605 ──┬── Deco Kitchen (main, wired) ── Deco Office   (wireless backhaul)
Megacable 750/750┘           │                                └ Deco Bedroom (wireless backhaul)
                             ├── navi        10.100.100.53
                             └── ocarina     10.100.100.50   (not built yet)
```

Everything that needs to be always-on lives in the kitchen, because the modems
are there and can't move. That includes navi, the future mini PC, and the UPS
when it arrives.

navi is wired directly to the ER605, not to a Deco. That's deliberate: a
monitoring box sitting behind a wireless backhaul reports the hop's flakiness as
ISP problems, and false alarms at 3am are how you teach yourself to ignore
alerts.

The router has five ports and they're spoken for. `WAN` and `WAN/LAN1` take the
two ISPs, one LAN port feeds the main Deco, navi has one of the remaining two and
ocarina will take the last. Anything after that needs a small switch.

## The two lines

| | Telmex | Megacable |
|---|---|---|
| Speed | 500/500 | 750/750 |
| ER605 port | `WAN` | `WAN/LAN1` |
| ER605 gets | `192.168.30.200` | `192.168.1.5` |
| Public IP | `187.211.43.253` | `189.196.218.19` |
| Inbound | yes, ONT has a DMZ to the ER605 | no, modem is ISP-locked |

Load balancing is bandwidth-weighted 500:750 with Application Optimized Routing
on. Link Backup is deliberately empty.

Megacable's public address is a real routable one, not carrier-grade NAT, which
means asking them for bridge mode would probably get a public IP straight onto
the ER605's WAN2. That would kill the double NAT and free the PS5 from being
pinned to Telmex. Worth a phone call, not yet made.

## Addressing

DHCP hands out `.100` to `.199` with a 120 minute lease. Everything below `.100`
is static or reserved, so there's no chance of collision.

| Address | Name | What |
|---|---|---|
| `.1` | `gate` | ER605 |
| `.20` | | Windows PC. Runs the music stack for now |
| `.30` / `.31` | | PS5 / PS Portal, pinned to Telmex by policy route |
| `.50` | `ocarina` | Mini PC, not built yet |
| `.53` | `navi` | This box. Mnemonic: DNS |
| `.54` | `tatl` | Second Pi-hole, planned |
| `.61` / `.62` | | Probe sources for the per-WAN checks |
| `.100` | | Main Deco |

`.53` is reserved on the ER605 rather than set statically on the Pi. Either would
work; the reservation keeps the whole map in one place.

## Names

Two layers, and the split matters.

Machines get Zelda names. `navi` shouts "Hey! Listen!" when something needs
attention, which is exactly what a monitoring box does. `tatl` is the other
fairy, which is why it's the second Pi-hole. `ocarina` plays the music. `chest`
will hold the NAS. `gate` is the drawbridge everything leaves through.

Functions get names so dull you can guess them at 2am with a dead network:
`help.lan`, `status.lan`, `dns.lan`, `router.lan`, `music.lan`. You shouldn't
have to remember which fairy was the router while you're trying to fix it, and
anyone else in the flat can find things without being taught the joke.

Both resolve. `music.lan` and `ocarina.lan` reach the same place.

The local domain is `.lan`. ICANN reserved `.internal` for private use in 2024
and it's arguably more correct, but it's longer and buys nothing here.

Bare hostnames also work on clients that honour the DHCP search domain, so
`http://status` is usually enough. Consoles and IoT devices tend to ignore it,
so anything written down should use the full `.lan` form.

## Per-WAN probe routing

`navi` carries two extra addresses on `eth0`, `.61` and `.62`. Two ER605 policy
routes pin `.61` to Telmex and `.62` to Megacable, which lets the monitoring test
each line independently instead of whatever the load balancer picks.

This only works over TCP. See [gotchas.md](gotchas.md).

## Things measured, so nobody re-argues them

Wired beats Wi-Fi by roughly 50x on jitter: 0.45 ms to a wired client on a
satellite versus 21.6 ms over Wi-Fi, even when that satellite's own backhaul is
wireless.

There's no bufferbloat. 698 Mbps down, 612 Mbps up, added latency under 1 ms. Don't
propose QoS shaping to fix a problem that isn't there.

The Decos are app-only. No usable web UI, no SNMP, no API. Anything you want to
know about the mesh, you get from the phone app or not at all.
