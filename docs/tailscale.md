# Tailscale, step by step

Not installed yet. This is the procedure for when it is.

Everything here happens on navi and in the Tailscale admin console. **The ER605,
both modems and the Decos are never touched**, so nothing in this document can
take the flat's internet down, and a power cut between any two steps costs you
nothing but the time already spent. Stop wherever you like.

The phases are ordered so that each one earns the right to do the next. Phase A
measures, Phase B proves remote access works at all, Phase C decides how much of
the house to expose, Phase D locks it down. Doing C before B is how you end up
debugging routing and NAT traversal simultaneously with no idea which is lying.

## Before you start

Have a Tailscale account. The free Personal plan covers 100 devices and 3 users,
which is more than this flat will ever need. Sign in with whatever identity
provider you'll still have in five years, because migrating a tailnet between
providers is genuinely annoying.

navi is Raspberry Pi OS Trixie, arm64. That matters for the repo path below.

---

## Phase A - install and measure

Nothing here changes any configuration outside navi. The entire point is to get
`netcheck` to answer the questions that an afternoon of traceroutes couldn't.

### A1. Install

```sh
ssh enrique@navi.lan
curl -fsSL https://tailscale.com/install.sh | sh
```

The script detects the distribution, adds Tailscale's apt repository and signing
key, and installs the `tailscale` package. That's all it does - it isn't an
opaque blob, and you can read it before running it if you'd rather.

If you'd sooner do it by hand, it's the same three steps, but **check that the
codename in those URLs matches `VERSION_CODENAME` in `/etc/os-release`** before
pasting anything. Raspberry Pi OS 64-bit identifies as Debian, so `debian/trixie`
is the right path; the `raspbian` repos are for the 32-bit builds.

One consequence worth knowing: this adds a new apt source, and per
[gotchas.md](gotchas.md) `unattended-upgrades` on this box is wider than the name
suggests and applies the general archive, not just security. Tailscale will
therefore auto-update. That's the behaviour you want here, but it's now true and
it wasn't before.

### A2. Bring it up

```sh
sudo tailscale up --accept-dns=false
```

**`--accept-dns=false` is not optional on this box.** Without it, Tailscale
rewrites `/etc/resolv.conf` on the machine that serves DNS for the entire flat.
Pi-hole runs in a container with its own resolver config so it would probably
survive, but "probably" is the wrong standard for the one service whose failure
is invisible until someone complains the internet is broken. navi has a perfectly
good resolver already. It's sitting on the same box.

The command prints a login URL. Open it, authenticate, and navi appears in the
admin console.

### A3. Turn off key expiry for navi

In the admin console, find navi in the machine list and disable key expiry.

By default node keys expire after 180 days. When navi's expires, remote access
stops working and nothing tells you - you find out the next time you need it,
which by construction is the moment you're away from the house. That is precisely
the silent-failure pattern this entire box exists to eliminate. Don't reintroduce
it on day one.

### A4. netcheck - the measurement this was all for

```sh
tailscale netcheck
```

Output looks roughly like:

```
Report:
	* UDP: true
	* IPv4: yes, 189.196.217.197:41641
	* IPv6: no, but OS has IPv6 address
	* MappingVariesByDestIP: false
	* PortMapping: UPnP
	* Nearest DERP: ...
	* DERP latency: ...
```

Four lines matter.

**`UDP: true`** - NAT traversal is possible at all. If this is false, everything
will relay and no amount of WAN work fixes it.

**`MappingVariesByDestIP`** - the dual-WAN tell, and the thing predicted in
[future-plans.md](future-plans.md). `true` means navi's STUN probes left by
different WANs and came back with different mapped addresses; Tailscale reads
that as a hard NAT and falls back to a DERP relay. Since ER605 policy routing is
TCP-only and Tailscale's data plane is UDP, the `.61`/`.62` trick cannot pin it.

**`IPv4:`** - whichever public address is shown tells you which line the load
balancer happened to pick for that probe. Run `netcheck` three or four times. If
the address alternates between the Telmex and Megacable publics, that's the load
balancer confirmed, independent of what the mapping line says.

**`Nearest DERP` and the latency table** - the relay you'd fall back to, and what
it would cost. Read it against the 9.3 ms versus 46.7 ms per-line split in
[network.md](network.md).

**Record the output in this file when you have it.** Everything downstream is
conditional on it, and re-deriving it later means another evening.

> **Safe stop.** navi is on the tailnet, nothing else has changed, and the flat's
> network is exactly as it was. If the weather turns, stop here.

---

## Phase B - prove it actually works remotely

### B1. Second device

Install the Tailscale app on your phone, sign in with the same account.

### B2. Test from LTE, not from the house

**Wi-Fi off on the phone.** Mobile data only.

Two Tailscale nodes on the same LAN discover each other locally and connect
direct, so a test run from the flat's Wi-Fi is green and completely meaningless -
the same false-green failure as the per-WAN ping monitors in
[gotchas.md](gotchas.md). Test it wrong and you'll believe remote access works
until the first time you need it.

From the phone, open `http://navi:8081` (Pi-hole's admin UI, on its host port).
Then check what kind of connection you got:

```sh
# on navi
tailscale status
```

Each peer shows `direct` or `relay "<derp>"`. `direct` means NAT traversal
worked despite the dual WAN. `relay` means it didn't, and the options in
[future-plans.md](future-plans.md) - firmware, IPv6 prefix delegation, or filling
in Link Backup - become live.

From a laptop that's off-network, `tailscale ping navi` shows the same thing per
packet, including the moment it upgrades from relayed to direct if it manages to.

> **Safe stop.** You now have working remote access to navi by its tailnet name.
> For SSH and the admin UIs that may honestly be enough, and Phase C is optional.

---

## Phase C - decide how much of the house to expose

This is a real decision, not a step. Two models, and the tradeoff is not obvious.

### Model 1: tailnet names only

Install Tailscale on each machine you want reachable. Devices get MagicDNS names
(`navi`) and `100.x` addresses. Nothing else in the flat is reachable at all.

Narrow, safe, and it needs no further configuration. But the PS5, the Decos, the
router UI and anything else that can't run a Tailscale client stay unreachable
forever.

The cost you'll notice first is certificates. Caddy's internal CA issues for
`.lan` names, so `https://navi` doesn't match anything and you'll get warnings or
fall back to plain HTTP. That in turn means no `navigator.mediaSession`, no
lock-screen controls - see [https.md](https.md) for why that's not a small loss.
`tailscale cert` can issue a real certificate for the `ts.net` name if you want
to solve it properly, but that's Caddyfile work.

### Model 2: subnet route plus split DNS

```sh
sudo tailscale up --accept-dns=false --advertise-routes=10.100.100.0/24
```

Then approve the route in the admin console - it does nothing until you do - and
in DNS → Nameservers, add navi's `100.x` address as a nameserver **restricted to
the `lan` domain**.

**These two halves are useless apart, and that's the part that isn't obvious.**
Split DNS makes `dns.lan` resolve remotely, and it resolves to `10.100.100.53`,
which a remote client cannot reach without the subnet route. Resolution without
routing gets you a name that answers and a connection that times out.

The good news is that Pi-hole needs no changes. `stack/pihole/docker-compose.yml`
already sets `FTLCONF_dns_listeningMode: 'ALL'` and publishes 53 on all host
interfaces, so queries arriving on `tailscale0` are answered once the interface
exists. This was the step most likely to bite and it's already done.

What Model 2 buys: every `.lan` name works remotely, with the existing
certificates, exactly as it does at home. It is the only model in which
`music.lan` works properly - it's HTTPS-only and Jean derives `foo_jean`'s
address from `window.location`, so it needs both the real name and reachability
to `10.100.100.20:8881`.

What it costs: it re-exposes the whole `/24`, including the two things
[future-plans.md](future-plans.md) has a standing rule about. beefweb has no
authentication at all and `foo_jean` rewrites files in the library. On the LAN
that's acceptable because the LAN is the flat. On the tailnet it's acceptable
only with Phase D done first.

**If you pick Model 2, do Phase D in the same sitting.** Not the next weekend.

---

## Phase D - ACLs

Default tailnet policy is allow-all between your own devices. That's fine while
the tailnet is navi plus your own phone and laptop. It stops being fine the
moment a subnet route lands, ocarina joins with the music stack on it, or you
share a node with anyone.

The rule from [future-plans.md](future-plans.md) transfers directly: never expose
SSH, beefweb or `foo_jean` to anything that doesn't need them. Tailnet ACLs are
that same rule in a different place, and "everyone on the tailnet" includes every
phone you will ever lose.

Write the policy in the admin console before the first remote connection that
could reach the music stack. Tag navi and ocarina as servers, tag your personal
devices, and grant explicitly rather than relying on the default.

---

## Rollback

Complete and instant, at any point:

```sh
sudo tailscale down                       # stop, keep it installed
sudo systemctl disable --now tailscaled   # stop it coming back
sudo apt remove tailscale                 # remove entirely
```

Then delete the machine from the admin console, or it sits there as a stale
entry. If you advertised subnet routes, they die with the node.

Nothing in this procedure modifies the ER605, so there is no router state to
restore and no config backup needed beforehand.

---

## To record here once it's done

- The `netcheck` output, verbatim.
- `direct` or `relay`, and from which networks you tested.
- Which model you picked in Phase C, and why.
- Whether Tailscale changed the answer to the Megacable bridge-mode question. It
  shouldn't - Tailscale works behind CGNAT - but if `netcheck` says `UDP: false`
  or the mapping varies, the call in [future-plans.md](future-plans.md) stops
  being about the PS5 and starts being about this.
