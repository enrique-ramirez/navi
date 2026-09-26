# Wi-Fi, and what's still wrong with it

Three Deco XE75 Pro in access point mode. Kitchen is the main node and the only one wired to the ER605; Office and Bedroom backhaul wirelessly.

## Roaming is the actual problem

Coverage is fine. Every device connected to any Deco reports a healthy link. The problem is switching between them.

Walk from the bedroom to the kitchen bar and a laptop clings to its original node until the connection is unusable, while a perfectly good Deco sits a metre away. Fast Roaming (802.11r), Beamforming and OFDMA are all on, which is everything the Deco app exposes.

The controls that would fix it are minimum RSSI thresholds, client steering aggressiveness, and 802.11v BSS transition tuning. **None of them exist in the Deco app.** They exist on Omada EAP access points.

So the honest options are: live with it and wire whatever matters, split a dedicated 5 GHz SSID and join fixed devices to it so band steering stops making decisions, or eventually replace the Decos with Omada EAPs. That last one would also unify everything under one controller, but it needs ethernet to each AP and right now only the main node is wired.

Nothing here is urgent. It's an annoyance, not a fault.

## Kitchen to Bedroom backhaul reads weak

The app shows Kitchen→Office as strong and Kitchen→Bedroom as weak. Deco picks parents automatically and can't be forced, so you can't route Bedroom through Office even if you wanted to.

Per the floorplan it's probably choosing correctly anyway: Bedroom sits above the Kitchen on the same side of the flat, while the Office is across the central dividing wall. Kitchen→Bedroom is likely the shorter RF path despite the weaker reading.

Worth trying: reposition the Bedroom node, since height and line of sight through a doorway matter more than distance through concrete. The bedroom TV is wired to that node, so its backhaul carries real traffic.

Measure rather than trusting the app's icon. From a client wired to the Bedroom Deco, `ping -c 100 10.100.100.1` and compare against the Office node, which measured 1.65/3.10/31.0/3.75 ms.

## Wiring the living room

Everything measured says cable beats Wi-Fi by roughly 50x on jitter, and wiring to a Deco satellite is nearly as good as wiring to the router.

Don't move the main Deco behind the TV. It's the root of the mesh, both other nodes backhaul through it, and it would end up in a dense pile of consoles against a concrete wall. Degrading it degrades everything.

Better: a small unmanaged switch fed from a Deco's spare port, wiring the TV, PS5 and whichever consoles stay put. That leaves the mesh topology alone.

For the PS5 specifically, powerline is worth considering if no cable route exists. It's ruled out for backhaul, but for a single device the calculation differs: even mediocre powerline gives 200-400 Mbps at a stable 2-5 ms, which comfortably beats contended Wi-Fi for Remote Play.

## 2.4 GHz congestion: plausible, untested

The living room holds an unusual density of 2.4 GHz transmitters. PS3, PS4, PS5, Switch 2, several Switch 1s, an Analogue 3D with two 8BitDo Bluetooth controllers plus two 2.4 GHz dongles, NT Mini Noir, Super NT, Superstation, two Analogue Pockets, and a pile of wireless controllers. Several sit in a low-power listening state while "off" so a controller can wake them.

Bluetooth and proprietary 2.4 GHz dongles share the band with 2.4 GHz Wi-Fi, and 8BitDo's receivers in particular have a reputation for being noisy. Many consoles are 2.4 GHz-only.

Against that: the clients that matter are on 5 GHz, which Bluetooth doesn't touch, and modern Bluetooth hops fast enough to coexist reasonably.

To test it properly, set 2.4 GHz to channel 1 at 20 MHz (a neighbour scan found 3, 5, 7, 10 twice, and 11 occupied, so channel 1 is clearest) and never 40 MHz on 2.4 GHz. Keep anything that matters on 5 GHz or cable. For a real answer you need a spectrum view, which a phone Wi-Fi analyser can't give you because it won't show Bluetooth at all. That needs a Wi-Spy or an SDR.

Treat it as a hypothesis. Nothing measured so far points at it.

## Small things still open

Confirm the 5 GHz 80 MHz change landed on a non-DFS channel. 36-48 is clean; 52-64 is where radar events cause 60-second blackouts.

Set 2.4 GHz to channel 1, 20 MHz.

## Don't re-debug: PS Portal couldn't reach the PS5

Fixed 2026-08-29, and **it was not a network problem.** Three network hypotheses were tested and all failed: load balancing splitting the two devices across different WANs, missing UPnP, and a stale cached console address.

The decisive measurement was the PS5 reporting NAT Type 2, meaning Sony's servers reached the console through the NAT. Type 2 is the normal healthy state for a console behind a router and is entirely sufficient for Remote Play. The empty UPnP portmap list is consistent with that, since the PS5 requests mappings on demand rather than persistently.

Most likely cause: the PS5 had been fully powered off during a power cycle, and the Portal can't reach a console that's off. It needs it on, or in rest mode with *Stay Connected to the Internet* and *Enable Turning On PS5 from Network* enabled.

That's a guess, not a proven cause. Several things changed at once and weren't isolated. The configuration was kept because it's correct regardless: the PS5 and Portal are reserved at `.30` and `.31`, grouped as `PlayStation`, and pinned to the Telmex WAN by policy route, since Telmex is the only line that can accept inbound.

## One operational warning

**The ER605 web UI locks out after 10 failed logins.** Worth remembering before any scripted access, or before guessing at the password.
