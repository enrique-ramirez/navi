# Monitoring

Thirteen monitors in Uptime Kuma at `status.lan`, all alerting to ntfy on the
phone. Six of them Kuma can run by itself; the other seven are pushed by
`wan-check.sh` every five minutes because Kuma can't see what they need to see.

## The monitors

| # | Name | Type | Catches |
|---|---|---|---|
| 1 | Telmex modem | ping | dead modem or cable |
| 2 | Megacable modem | ping | same, other line |
| 3 | ER605 | ping | router down |
| 4 | Google `8.8.8.8` | ping | total internet loss |
| 5 | Cloudflare `1.1.1.1` | ping | total internet loss |
| 6 | Telmex LINE | push | **one ISP silently dying** |
| 7 | Megacable LINE | push | same, other line |
| 8 | DNS resolver | dns | resolver death, which looks like "internet is down" |
| 9 | Blocking active | push | Pi-hole resolving but no longer blocking |
| 10 | Gravity freshness | push | blocklist quietly going stale |
| 11 | Needs attention | push | pending reboot, full disk, updates gone quiet |
| 12 | SSH attempts | push | something on the LAN trying to get into navi |
| 13 | Temperature | push | cooling regressing, or the PSU sagging |

## Why the obvious checks aren't enough

Pinging a modem proves the modem is alive. It doesn't prove the ISP is
delivering anything, because the ONT is powered by you and keeps answering pings
happily throughout an upstream outage. Monitor 1 would not have caught the
two-week Telmex failure.

Pinging `8.8.8.8` is worse for this purpose. It follows the load balancer, so it
stays green while either line works. That's the exact blind spot that let the
outage run for a fortnight.

Monitors 6 and 7 are the ones that matter. Everything else is context.

## How the per-WAN checks work

`navi` has two extra IPs on `eth0`. ER605 policy routes pin `.61` to Telmex and
`.62` to Megacable. Every five minutes, `wan-check.sh` fetches the egress public
IP from each source address and confirms it belongs to the ISP that line is
supposed to use.

That confirmation is the interesting part. The check proves its own path on every
run. If a policy route breaks, the monitor goes down with `WRONG LINE` rather
than quietly re-testing the surviving line and staying green. A monitor that
can't tell you it's measuring the wrong thing is worse than no monitor.

It's HTTP rather than ping, and that isn't a preference. The ER605 only applies
policy routing to tracked TCP sessions; UDP and ICMP fall back to load balancing
even with Service Type set to ALL. A `ping -I` version of this check would sit
green while testing whichever line the router felt like. Details in
[gotchas.md](gotchas.md).

## Why the check matches the ISP and not the address

It used to compare against a literal public IP per line, held in `WAN1_EXPECT`
and `WAN2_EXPECT`. That was wrong, and it took a power cycle to find out: the
cables were unplugged for tidying on 2026-09-04, both lines came back on new
addresses, and both monitors went red over a network that was working perfectly.

Neither ISP gives us a static address. Nothing in the house had noticed because
nothing depends on the public IP - no port forwarding, no DDNS - so the first
thing to care was the monitor, and what it reported was a lie in the most
expensive direction. A monitor that cries wolf after every power cut is one you
learn to dismiss, and the whole point of this box is a monitor you believe.

What is stable is the ISP. Both put their own domain in the reverse DNS and kept
it across the lease change:

| | before | after |
|---|---|---|
| Telmex | `187.211.43.253` | `187.213.253.225` |
| | `dsl-…-dynamic.prod-infinitum.com.mx` | same suffix |
| Megacable | `189.196.218.19` | `189.196.217.197` |
| | `customer-GDL-CGN-….megared.net.mx` | same suffix |

So `WAN1_ISP` and `WAN2_ISP` hold a PTR substring instead, and the check asks
"did this leave by Telmex" rather than "did this leave from one exact address".

**This is more informative than what it replaced, not just more durable.**
`egress X expected Y` said exactly the same thing whether the lease had renewed
or the line had died, which meant it couldn't distinguish the harmless case from
the one the box exists for. A PTR belonging to the *other* ISP can only mean
traffic pinned to this line is leaving by the other one, and that is the router
having failed over - the silent ISP death, caught and named.

**When the PTR can't be read it degrades instead of going red.** If the lookup
fails, or `.env` hasn't been given the domains yet, the check falls back to a
weaker invariant: two different ISPs cannot hand out the same public address, so
if both source aliases egress the same one, policy routing has stopped
separating them. That still catches a collapsed route. It cannot catch the two
lines being swapped, so the message says `ISP unverified` rather than implying a
confidence it doesn't have.

**A changed public IP is not itself an alert.** It's in the message on every
push, so Kuma's history has it, but nothing in the flat depends on that address
and paging you about a DHCP renewal is how monitors become wallpaper. If
anything ever does depend on it - a Tailscale exit node, a port forward - that
changes and it becomes worth its own monitor.

## Alerting

ntfy, public `ntfy.sh`, with a 20-character random topic. Topics are
unauthenticated and world-readable, so the topic string is the only thing keeping
your alerts private. It's in 1Password.

Public rather than self-hosted, on purpose. An alerting service running on the box
it's meant to be watching can't tell you that box has died. The notification path
must not share a failure domain with the thing it monitors, which is the same
reason the help page answers on a bare IP.

Priority 3 for normal events, 4 for outages. Not 5. Priority 5 bypasses Do Not
Disturb on Android, and one ISP dying at 3am doesn't warrant waking you: the house
keeps working on the other line, which is the entire point of having two. If
everything is priority 5 you'll swipe alerts away half-asleep and miss the one
that matters.

Save 5 for something genuinely urgent, like both lines down at once, or the
resolver dying. Neither monitor exists yet.

## Two monitors that look redundant and aren't

Monitor 9 checks that Pi-hole still blocks. A wiped blocklist looks identical to a
healthy resolver from every other angle: DNS answers, uptime is perfect, nothing
goes red, ads just come back. It queries two known-blocked domains and only
alarms if both resolve, because lists legitimately drop individual domains and a
single canary will eventually cry wolf.

Monitor 10 checks the blocklist's age. Gravity updates weekly from cron inside
the container. If that fails, Pi-hole keeps serving the old list and says nothing.
The threshold is 10 days, so one missed run is tolerated and two aren't, plus a
floor on the domain count to catch an "update" that successfully downloaded an
error page.

## The status panel on help.lan

Ten tiles on the landing page: temperature, uptime, load, memory, disk,
network throughput, container states, timer health, and the age of the last
backup, and the last SSH login. `host-status.timer` samples them every 28
seconds into
`/srv/data/www/host.json`; the page re-reads that file every 30 seconds and
whenever the tab regains focus, so it updates without a manual refresh.

It is a **view, not an alarm**. Nothing here notifies. Kuma notifies. This is
the page you open once something has already told you to look, or when someone
in the flat says the internet feels slow and you want to know within five
seconds whether navi is the reason.

Same architecture as the repo-status banner, for the same reason: a timer writes
a static file, Caddy serves it, the browser reads it. There is no endpoint.
`host-status.sh` runs as root, and the distance between "a page that shows you
root's view of the box" and "a page that lets the LAN ask root questions" is the
entire security model.

## What the panel deliberately doesn't have

**No log tail.** It's the obvious next feature and it's a bad one. A journal
excerpt on an unauthenticated page reachable by everything on the LAN is an
information-disclosure surface that grows every time some service decides to log
a token, and it isn't how debugging actually works: you SSH in and read the
whole unit with context. What's on the panel instead is the derived half - is
the timer active, did the last run succeed, when did it finish - which is the
part you want at a glance and which cannot leak a secret.

**No speed test.** "Network speeds" sounds like it should mean a throughput
test, and a throughput test on a timer would saturate the line it's measuring,
every minute, forever. The tile shows interface counters sampled two seconds
apart, which is what navi is actually moving right now. The ISP lines are
already measured end to end by monitors 6 and 7; nothing else in the house could
tell you navi itself is the bottleneck.

**No SMART.** The SSD's health is worth watching and doesn't belong here.
Reallocated sectors move on a scale of months, `smartctl` on this enclosure
needs `-d sat` (see [navi.md](navi.md)), and a value that changes four times a
year has no business being re-read sixty times an hour. It belongs in a daily
check that can push to Kuma. Not built yet.

**No thresholds that disagree with wan-check.** The disk tile turns amber at
85%, which is the number `wan-check.sh` already alerts on. Two different
thresholds for one condition is how you end up trusting neither.

## Two things the panel notices that nothing else does

**Throttling since boot.** `vcgencmd get_throttled` bits 16-19 record that
under-voltage or thermal throttling happened at some point, even if conditions
are fine by the time you look. After the case and copper block that word should
read `no throttling` forever, so if it ever doesn't, the cooling has regressed
or the PSU has started sagging. Nothing else in the house keeps that record.

**A backup that stopped happening.** `wan-check.timer` dying is loud: six push
monitors go stale and Kuma shouts. `navi-backup.timer` dying is completely
silent, and would stay silent until the day you needed a restore. The backup
tile turns amber at 36 hours and red at three days. This is the single most
useful thing on the panel and the reason it got built at all.

## Monitor 12, and why it counts so little

SSH here is key-only, root login is off, and it is never port-forwarded. Nothing
outside the flat can reach port 22 at all, so this monitor is not about the
internet. It's about the LAN: a rejected attempt means something already inside
the house is trying doors, which is a compromised IoT device or a guest's laptop
rather than a bot in another country.

**It does not alarm on successful logins,** and that's deliberate. The only
person who can log in is you, so an alert on every success would be you paging
yourself during routine maintenance. Priority 5 is reserved for things that
warrant waking you; an alert that fires whenever you work becomes wallpaper, and
then so does everything next to it.

**"Failed publickey" is deliberately not counted.** ssh clients offer every key
they hold and each rejected offer logs that line, so one entirely normal login
by you can produce two or three. A threshold over those would fire constantly.
What's counted is what cannot be you: `Invalid user`, `Failed password` (which
can't legitimately occur, since password auth is off), and clients that burned
through `maximum authentication attempts exceeded`. On this network the normal
reading is zero, so the alarm sits at five in 24 hours.

**Matched by syslog identifier, not by unit.** Trixie socket-activates ssh into
per-connection units, and OpenSSH 9.8+ moved authentication into a separate
`sshd-session` binary, so a `journalctl -u ssh` version of this check would miss
exactly the lines that matter and report a confident zero forever. Both `sshd`
and `sshd-session` are matched, and the check first proves it can see *any* sshd
line before believing a count of none. If it can't, it says so instead.

Worth confirming on the box once: `journalctl -t sshd -t sshd-session -n 5`
should return something. If it doesn't, the identifier has moved again.

The count is computed here, on the five-minute timer, and left in
`/srv/data/ssh-fail` for the panel to read. A `journalctl` call is by a wide
margin the most expensive thing `host-status.sh` could do, and a 24-hour count
has no business being recomputed every 28 seconds.

This monitor becomes considerably more interesting the day Tailscale lands.
Right now it watches a door that only opens from inside the flat.

## Monitor 13, the one the panel couldn't make

Temperature has been on the landing page since day one, and the page is a view.
Nobody watches a view. The copper block working loose, a summer afternoon in a
kitchen, dust in a passive case: all of them arrive as a number nobody is
looking at, and the first symptom you'd actually notice is the box throttling
and the flat saying the internet feels slow.

**75 °C, not the SoC's 80 °C cap.** Assembled, navi peaks at 51.1 °C with all
four cores pinned ([navi.md](navi.md)), so anything near 75 is the cooling
having regressed rather than the box being busy. An alarm set at the cap fires
after the throttling it was meant to prevent; this one has 24 °C of headroom
over the worst load this machine has ever seen and still leaves 5 °C before the
firmware does anything.

**The since-boot throttle bits are deliberately not an alarm condition.** They
never clear until a reboot, so a monitor that went down on them would sit red
for a fortnight over one bad afternoon and be ignored by the end of the first
day. They ride along in the message instead, which is where the panel already
puts them. What does alarm is the "right now" half of the word: currently
throttling, or currently under-voltage - and the message says which, because
under-voltage is the power supply sagging and sends you to a different shelf
than a heat problem does.

**An unreadable thermal zone is not 0 °C.** It pushes down with `cannot read the
thermal zone`, for the same reason the SSH check proves it can see the journal
before believing a count of none. A comfortable zero from a sensor that has
stopped answering is exactly the failure shape this box was bought to catch.

The tile on `help.lan` turns amber at 65 and red at 75, the same two numbers.
Two thresholds for one condition is how you end up trusting neither.

## Why the writer is faster than the reader

28 seconds against a 30-second poll, and the mismatch is the point. Two clocks
on the same period can settle into an unlucky phase and stay there, every read
landing just before a write, so you permanently look at numbers a full period
old. A writer that runs slightly faster makes the offset precess instead: the
age of what's on screen sweeps the range rather than sticking at the worst end.

What is *not* being compensated for is the 2 seconds the script spends sampling
network counters. `OnUnitActiveSec=` measures from activation, not completion,
so runtime sits inside the period rather than adding to it.

`AccuracySec=1s` is the load-bearing part. The default is a minute, and even 10
seconds would let systemd defer the timer into a 29-39 second swing, which is
worse than having no offset at all. The cost is a few timer wakeups an hour
that can't be batched with anything else, on a box that didn't flinch with all
four cores pinned.

Change one of the two numbers and change the other. A writer slower than the
reader is the single arrangement that makes the panel consistently stale.

## The staleness banner

If `host.json` is more than two minutes old the panel says so, in red, above
the tiles. This matters more than any individual number on it.

Two minutes is about four missed samples: enough that a single skipped run or a
slow tick can't cry wolf, little enough to notice within a couple of minutes.

A status display whose data source has died shows its last good reading forever,
and a frozen 38 °C looks exactly like a healthy 38 °C. That's the silent-failure
bug this entire project exists to fix, and building a new instance of it on the
front page would be a poor joke. The panel would rather tell you it doesn't know.

## Testing

Every alert path here has been fired deliberately, not assumed.

Removing the `.61` alias produced `PENDING → DOWN` on the Telmex monitor while
Megacable stayed up, then clean recovery. Dropping the gravity threshold to -1 day
fired the staleness alert and recovered. Both reached the phone.

The two newest paths, to fire the same way:

```sh
# WRONG LINE: point one line at the other ISP's domain and wait a tick
sudo sed -i 's/^WAN1_ISP=.*/WAN1_ISP=megared.net.mx/' /srv/navi/.env
# temperature: drop the alarm to below idle
sudo sed -i 's/^TEMP_ALARM=75/TEMP_ALARM=30/' /usr/local/bin/wan-check.sh
```

Put both back afterwards. `TEMP_ALARM` lives in the deployed copy of the script,
so `deploy.sh` will overwrite that edit on the next run anyway, which is the
right way round.

Do this after any change to the alerting path. An alarm that has never fired isn't
an alarm, it's a decoration.

One thing worth checking after adding any monitor:

```sh
sqlite3 kuma.db 'select count(*) from monitor'
sqlite3 kuma.db 'select count(*) from monitor_notification'
```

If those numbers differ, something has no way to reach you. "Apply on all
existing monitors" only applies to monitors that existed when you ticked it, and
two push monitors were silently alert-less for a while because of exactly that.
