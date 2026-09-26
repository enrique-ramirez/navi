# The house network

## Shape of it

Two ISPs land in the kitchen. Both terminate on a TP-Link ER605, which does the routing and load balancing. Wi-Fi is three Deco XE75 Pro units in access point mode, so the Decos are dumb radios and the ER605 makes every decision.

```
Telmex 500/500 ──┐
                 ├── ER605 ──┬── Deco Kitchen (main, wired) ── Deco Office   (wireless backhaul)
Megacable 750/750┘           │                                └ Deco Bedroom (wireless backhaul)
                             ├── navi           10.100.100.53
                             └── hyrule-castle  10.100.100.50
```

Everything that needs to be always-on lives in the kitchen, because the modems are there and can't move. That includes navi, hyrule-castle, and the UPS when it arrives.

navi is wired directly to the ER605, not to a Deco. That's deliberate: a monitoring box sitting behind a wireless backhaul reports the hop's flakiness as ISP problems, and false alarms at 3am are how you teach yourself to ignore alerts.

The router has five ports and they're spoken for. `WAN` and `WAN/LAN1` take the two ISPs, one LAN port feeds the main Deco, navi has one of the remaining two and hyrule-castle takes the last. Anything after that needs a small switch.

## The two lines

| | Telmex | Megacable |
|---|---|---|
| Speed | 500/500 | 750/750 |
| ER605 port | `WAN` | `WAN/LAN1` |
| ER605 gets | `192.168.30.200` | `192.168.1.2` |
| Public IP | dynamic, `prod-infinitum.com.mx` | dynamic, `megared.net.mx` |
| Inbound | yes, ONT has a DMZ to the ER605 | no, modem is ISP-locked |

Load balancing is bandwidth-weighted 500:750 with Application Optimized Routing on. Link Backup is deliberately empty.

**Neither address is static.** Both changed after the cables were unplugged on 2026-09-04, which is what broke monitors 6 and 7 and got them rewritten to match the ISP's reverse DNS instead of a literal address. Nothing else in the flat depends on the public IP - no port forwarding, no DDNS - so this costs nothing today, but it's the first thing to check against any future plan that assumes an address stays put.

Asking Megacable for bridge mode would kill the double NAT and free the PS5 from being pinned to Telmex. Worth a phone call, still not made. **Probed on 2026-09-07 and still unresolved** - [future-plans.md](future-plans.md) has the test that would settle it and what to ask.

The evidence is genuinely split. As measured on 2026-09-07, `189.196.217.197` resolved to `customer-GDL-CGN-217-197.megared.net.mx`, and `CGN` in an ISP's own hostname usually means carrier-grade NAT. That address has since changed - it was `189.196.209.57` on 2026-09-21 - so re-read the PTR before leaning on it; the pattern is the evidence, not the number. But a TCP traceroute from `.62` finds no `100.64/10` anywhere, which is the one unambiguous marker, and the HSI connection is native dual-stack rather than DS-Lite, which would have been carrier NAT by construction. Hops 3 to 8 are all RFC1918 `10.x`, and that proves nothing in either direction: carriers number access networks in `10.x` routinely, some run CGNAT out of `10/8` instead of the reserved range, and a traceroute cannot show where translation happens - it shows the interfaces that answered, not the boundary.

The ZTE's WAN status page confirms `NAT: On` and a seven-day DHCP lease, but **does not show the WAN address**. Those fields exist in ZTE's firmware; the `Mega_FA86` customer login doesn't render them. Not being able to read your own WAN address is the reason this is still open.

## IPv6

Both lines deliver it. Neither delivers it anywhere useful yet.

| | ER605 WAN address |
|---|---|
| Telmex | `2806:102e:29:7d23:c206:c3ff:fef0:5841/64` |
| Megacable | `2806:261:482:112:c206:c3ff:fef0:5842/64` |

`2806::/16` is LACNIC space, so those are real global addresses, not ULA. The host halves are EUI-64 derived from the WAN MACs - `C0-06-C3-F0-58-41` becomes `c206:c3ff:fef0:5841` once you flip the universal bit and insert `FF:FE` - which tells you the mechanism is SLAAC.

That distinction is the whole story. SLAAC gives the ER605 one address for its own WAN interface. It is not a delegated prefix, and only a delegated prefix gives the router something to hand out. So navi has nothing but `fe80::`, `curl -6` has no route to try and exits 7, and IPv6 stops dead at the router.

Worth fixing if Tailscale ends up relaying, because IPv6 has no carrier NAT and a global address at both ends deletes the traversal problem rather than working around it. Two things would have to be true and neither is confirmed: the upstream box has to do DHCPv6-PD rather than just advertising its own /64, and the ER605 has to request it.

If it is fixable, delegate from Telmex only. IPv6 has no NAT, so two prefixes on one LAN means clients choose source addresses themselves and no policy route can make that choice match the WAN you wanted. Dual-WAN IPv6 is a different and worse problem than dual-WAN IPv4, not the same one again.

## Addressing

DHCP hands out `.100` to `.199` with a 120 minute lease. Everything below `.100` is static or reserved, so there's no chance of collision.

| Address | Name | What |
|---|---|---|
| `.1` | `gate` | ER605 |
| `.20` | | Windows PC. Runs the music stack for now |
| `.30` / `.31` | | PS5 / PS Portal, pinned to Telmex by policy route |
| `.50` | `hyrule-castle` | Mini PC. Holds the services |
| `.51` | | hyrule-castle's WiFi, recovery path only |
| `.53` | `navi` | This box. Mnemonic: DNS |
| `.54` | `tatl` | Second Pi-hole, planned |
| `.61` / `.62` | | Probe sources for the per-WAN checks |
| `.100` | | Main Deco |

`.53` is reserved on the ER605 rather than set statically on the Pi. Either would work; the reservation keeps the whole map in one place.

## Names

Two layers, and the split matters.

Machines get Zelda names. `navi` shouts "Hey! Listen!" when something needs attention, which is exactly what a monitoring box does. `tatl` is the other fairy, which is why it's the second Pi-hole. `hyrule-castle` holds things, which is what a box running every service does. `chest` will hold the NAS. `gate` is the drawbridge everything leaves through.

Functions get names so dull you can guess them at 2am with a dead network: `help.lan`, `status.lan`, `dns.lan`, `router.lan`, `music.lan`. You shouldn't have to remember which fairy was the router while you're trying to fix it, and anyone else in the flat can find things without being taught the joke.

Both resolve. `music.lan` and `ocarina.lan` reach the same place.

`ocarina` is the one name that sits on the function side rather than the machine side. It was originally meant to be the mini PC, and stopped fitting once that box grew a film library and a photo library - a castle holds things, an ocarina plays music. So the machine is `hyrule-castle` and `ocarina.lan` survives as an alias of `music.lan`, which is what it always described anyway. Nothing pointing at `ocarina.lan` had to change.

The local domain is `.lan`. ICANN reserved `.internal` for private use in 2024 and it's arguably more correct, but it's longer and buys nothing here.

Bare hostnames also work on clients that honour the DHCP search domain, so `http://status` is usually enough. Consoles and IoT devices tend to ignore it, so anything written down should use the full `.lan` form.

## Per-WAN probe routing

`navi` carries two extra addresses on `eth0`, `.61` and `.62`. Two ER605 policy routes pin `.61` to Telmex and `.62` to Megacable, which lets the monitoring test each line independently instead of whatever the load balancer picks.

This only works over TCP. See [gotchas.md](gotchas.md).

## Things measured, so nobody re-argues them

Wired beats Wi-Fi by roughly 50x on jitter: 0.45 ms to a wired client on a satellite versus 21.6 ms over Wi-Fi, even when that satellite's own backhaul is wireless.

There's no bufferbloat. 698 Mbps down, 612 Mbps up, added latency under 1 ms. Don't propose QoS shaping to fix a problem that isn't there.

**The kitchen LAN is sub-millisecond**, measured 2026-09-21 from hyrule-castle on the ER605's fifth port: 0.697 ms average to the router, 0.291 ms to navi, 0.069 ms of deviation. Set that against the `1.65/3.10/31.0/3.75 ms` a wired client on the Office Deco measures in [wifi.md](wifi.md) - 27x the worst case and 27x the jitter, because of one wireless backhaul hop. Wiring to the router is not a marginal improvement over wiring to a satellite.

navi answers faster than the router does. That's expected: LAN-to-LAN crosses the ER605's switch fabric, while pinging the router hits its management CPU, which deprioritises ICMP. Don't read it as the router being slow.

**Gigabit is the LAN ceiling and nothing on the shopping list changes that.** The ER605's LAN ports are 1 GbE. hyrule-castle has dual 2.5 GbE and the Deco XE75 Pro has 2.5 GbE ports, so it is tempting to think there is headroom to unlock by choosing the right jack. There isn't: every path between two machines here crosses the ER605 or a Deco uplink to it. The dual 2.5 GbE on the mini PC is decorative.

**The two lines are not interchangeable for latency.** TCP traceroute to `1.1.1.1` from `.61` and `.62`, 2026-09-07:

| | to `1.1.1.1` | Path |
|---|---|---|
| Telmex | 9.3 ms | public at hop 3, straight into Uninet |
| Megacable | 46.7 ms | six RFC1918 hops, 33 ms of it before leaving Megacable |

Megacable exits via Transtelco near the Juárez border rather than peering in Guadalajara, and has already burned 33 ms inside its own network by hop 5. Both figures are TCP, so neither is subject to the ICMP problem in [gotchas.md](gotchas.md). Prefer Telmex for anything latency-sensitive, and treat any unpinned measurement of "the internet" from here as a coin flip between the two.

The Decos are app-only. No usable web UI, no SNMP, no API. Anything you want to know about the mesh, you get from the phone app or not at all.
