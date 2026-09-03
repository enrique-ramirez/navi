# Monitoring

Eleven monitors in Uptime Kuma at `status.lan`, all alerting to ntfy on the
phone. Five of them Kuma can run by itself; the other six are pushed by
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
IP from each source address and compares it to what it should be.

That comparison is the interesting part. The check proves its own path on every
run. If a policy route breaks, the monitor goes down with `ROUTE BROKEN - egress
X expected Y` rather than quietly re-testing the surviving line and staying
green. A monitor that can't tell you it's measuring the wrong thing is worse than
no monitor.

It's HTTP rather than ping, and that isn't a preference. The ER605 only applies
policy routing to tracked TCP sessions; UDP and ICMP fall back to load balancing
even with Service Type set to ALL. A `ping -I` version of this check would sit
green while testing whichever line the router felt like. Details in
[gotchas.md](gotchas.md).

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

## Testing

Every alert path here has been fired deliberately, not assumed.

Removing the `.61` alias produced `PENDING → DOWN` on the Telmex monitor while
Megacable stayed up, then clean recovery. Dropping the gravity threshold to -1 day
fired the staleness alert and recovered. Both reached the phone.

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
