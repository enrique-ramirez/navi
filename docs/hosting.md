# Everything outside the flat

Domains, email, the public websites, and the offsite copy of the data. The rest of these docs cover what runs in the kitchen. This one covers what runs somewhere else and why it isn't being brought home.

Prices here are approximate and from late 2026. Check them before committing to anything; the reasoning is the durable part, not the numbers.

## The test is exit cost, not vendor size

The instinct is to count how much Google is in the stack and try to make the number smaller. That's the wrong measure. The right one is: if this vendor turned hostile, tripled its price, or locked the account tomorrow, how long would it take to leave?

Some layers are commodity and the answer is an afternoon. Static hosting, DNS, object storage. Vendor size genuinely doesn't matter there, and paying a big one for reliability is a good trade. Other layers are sticky, and those are the ones worth being careful about.

Under this test the current setup is already mostly right, and the thing that makes it right is the domain.

## The domain is the portability layer

Gmail on `enrique-ramirez.com` is not lock-in. Mail on `@gmail.com` would be. The difference is entirely that the address is owned, which turns a migration into a weekend of DNS records and an IMAP sync rather than telling several hundred people you have a new identity.

That single fact is what makes every decision below cheap. It's also why the registrar matters more than anything hanging off it, and why the registrar gets its own account.

## Email stays with a vendor, and self-hosting it is out

Not "not yet". Out.

Deliverability is a reputation game refereed by Google and Microsoft, played from a residential Mexican IP that is almost certainly on a consumer block list already. The failure mode isn't bounced mail, which you'd notice. It's sent mail silently landing in spam for months, which is the same silent-failure bug this entire project exists to fix, aimed at the one account that resets every other password.

Google Workspace stays for now. Business Starter is roughly $7/user/month for a single mailbox, which is fine for what it does. The meaningful de-Google move, if it's ever wanted, is Fastmail at around $5/month or Migadu: paid vendors whose incentive is the subscription rather than the data.

Not now, though. `future-plans.md` says four migrations at once is how self-hosting projects die. The music server, the NAS and the first offsite copy are all in flight. Mail is working. Revisit once the house stack has been boring for a few months.

## Nothing consolidates into Google

The tempting move is to make more use of a Workspace account that's already being paid for: move the domains in, move the site to GCP, use Drive as the offsite backup. It's the wrong direction, for two reasons.

The first is the failure domain. Registrar, DNS, mail, storage and hosting in one account means one automated flag takes the identity, the email, the website and the backups simultaneously, with no support line to call. Right now those failures are independent, which is worth more than the convenience of a single bill.

The second is track record. Google ran Google Domains, then sold the business to Squarespace in 2023 and migrated everyone off it. The free Workspace tier was withdrawn. Unlimited Photos was withdrawn. Standardising on the vendor with the strongest history of leaving the market is a strange way to reduce dependence on vendors.

GCP specifically buys nothing here. A static site doesn't need IAM, and it doesn't need a billing surface with no hard spend cap attached to a personal card.

## Registrar separate from DNS separate from hosting

Move both domains to a registrar that only does registration: Cloudflare Registrar, which sells at cost and doesn't play renewal-price games, or Porkbun. DNS at Cloudflare. Hosting somewhere else again.

This isn't a complaint about Dreamhost, which is a perfectly good registrar. It's that registrar, DNS, mail and hosting currently sit in one account, and that account is the root of the whole identity. Splitting them costs nothing and removes the single point of failure.

## The websites are static and they live off-site

`enrique-ramirez.com` and, eventually, `ingosranch.com` go on Cloudflare Pages or Netlify, deployed from a git repo. Free, and it matches the workflow already in use everywhere else here: edit, commit, push.

They don't get self-hosted in the flat. Telmex is the only line that accepts inbound, the standing rule against port-forwarding still applies, and a public web presence shouldn't inherit the uptime of a flat with two consumer ISPs and a Pi. Cloudflare Tunnel would work around the inbound problem but not the second one.

## Offsite backup is object storage, not Drive

Drive is a sync product wearing a backup costume. Versioning is weak, there's no immutability, and `rclone` to Drive runs into a 750 GB/day upload ceiling plus API quota errors that make the initial seed genuinely painful. Per terabyte it's also the worst of the three, since the useful tier is 2 TB pooled at roughly $14/user/month.

| Target | ~/TB/month | Notes |
|---|---|---|
| Hetzner Storage Box | ~€3.80 | best value, native restic/borg/rclone/sftp |
| Backblaze B2 | ~$6 | S3-compatible, object lock against ransomware |
| Google Drive | ~$7+ | wrong tool, 2 TB minimum tier, painful at scale |

The footprint is smaller than it looks, because the replaceability tiering in `future-plans.md` already applies: music, photos and documents get paid for, the film library doesn't. Call it 600-800 GB, so roughly $4-5/month.

Timing is unchanged from `future-plans.md`. This starts when the music lands on hyrule-castle, not when the NAS arrives, because that's the window where 419 GB exists exactly once on a consumer NVMe in a flat.

The eventual friend-to-friend sync is a third copy and a good one, but it's best-effort and it doesn't get to be the only offsite.

## ingosranch stays small and stays isolated

Static site generator, its own repo, its own hosting account, a holding page until there's something to put behind it.

Two reasons for the isolation. Treating a side project as an infrastructure project is how it stays on hold for another five years. And a Zelda fan site carries real Nintendo takedown risk, which is not something that should ever arrive at the account holding the email.

## What's settled and what isn't

Settled: no self-hosted mail, no consolidation into Google, no GCP, no Drive as a backup target, public sites stay off-site and static, registrar split from everything else.

Open, in rough order. Move the two domains to a dedicated registrar. Stand up the first offsite backup when the music migration completes. Decide about Fastmail or Migadu once the house stack has been quiet long enough that a mail migration is the only thing in flight.
