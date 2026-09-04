# When something breaks

## Read this first

If Pi-hole is down, no `.lan` name resolves, including `help.lan`. Two ways in
that don't depend on it:

`navi.local` works over mDNS, which is handled by avahi on the Pi and never
touches Pi-hole. `ssh enrique@navi.local` and `http://navi.local` both work with
DNS completely dead. This is the easy one, and it's why avahi is left running.
It's reliable from macOS, Linux and iOS; Android's mDNS support is patchy, so
don't count on it from the phone.

`http://10.100.100.53` always works. Worth writing on a label and sticking to
the Pi, for the case where you're on a device that can't do mDNS.

If the network is down badly enough that you can't reach either, this file is on
GitHub and on your laptop.

## "The internet is down"

Open `http://10.100.100.53:3001`. Kuma answers on its own port, so it works even
when Caddy or DNS don't.

If `DNS · navi resolver` is red, it's name resolution, not connectivity. There's
deliberately no secondary DNS, so a dead Pi-hole is indistinguishable from a dead
internet for every device in the flat.

If both `LINE` monitors are red, it really is both ISPs, which has never
happened. If one is red, the house is fine and you have no spare until it's fixed.

## Getting online right now, bypassing navi

Set your laptop's DNS to `1.1.1.1` by hand. You lose ad blocking and `.lan` names,
everything else works. Undo it afterwards or you'll wonder in a month why ads are
back.

## Pi-hole won't start / DNS is dead

```sh
ssh enrique@navi.local          # mDNS, works with DNS dead
docker ps -a | grep pihole
docker logs pihole --tail 50
cd /srv/navi/stack/pihole && docker compose --env-file /srv/navi/.env up -d
```

If the container is fine but resolution isn't, check that port 53 isn't taken:

```sh
sudo ss -lnup | grep :53
```

## A site is broken and you suspect blocking

Query log at `dns.lan`. Search the domain. If it shows as blocked, allowlist it
there. That's a UI action and doesn't need a deploy.

If it turns out to be a whole category of breakage, the blocklist choice is in
[decisions.md](decisions.md); dropping back to a lighter HaGeZi tier is a one-word
change in `.env`.

## "ROUTE BROKEN" alert

The ER605 policy route for `.61` or `.62` stopped working, so a per-WAN check is
measuring the wrong line. Monitoring is degraded, the network is fine.

Check the rules under Transmission → Routing → Policy Routing, then verify:

```sh
curl -s --interface 10.100.100.61 https://api.ipify.org   # expect 187.211.43.253
curl -s --interface 10.100.100.62 https://api.ipify.org   # expect 189.196.218.19
```

If the aliases are missing entirely, `ip -br addr show eth0` will show it. They're
persisted in NetworkManager on the `Wired connection 1` profile.

## "navi · needs attention"

The message says which. Usually a security update wants a reboot:

```sh
ssh enrique@10.100.100.53 'cat /var/run/reboot-required.pkgs'
sudo systemctl reboot
```

Reboots take about 40 seconds, during which the whole flat has no DNS. Do it when
nobody's mid-call.

## navi won't boot

Pull the SSD. `BOOT_ORDER=0xf14` falls back to the SD card, which holds a
complete system, and the flat gets DNS back. Then debug the SSD at your leisure:

```sh
sudo smartctl -a -d sat /dev/sda    # note the -d sat
```

## Rebuilding from nothing

1. Image Raspberry Pi OS Lite 64-bit. Put an empty file named `ssh` and a
   `userconf.txt` containing `username:hash` on the boot partition. Do not use
   `custom.toml`; see [gotchas.md](gotchas.md).
2. Install Docker.
3. Generate a fresh deploy key and add it to the repo on GitHub as read-only.
   The old one isn't backed up anywhere on purpose, because regenerating it is
   quicker than keeping another copy of a private key:

   ```sh
   ssh-keygen -t ed25519 -f ~/.ssh/navi_deploy -N "" -C "navi deploy key"
   cat ~/.ssh/navi_deploy.pub    # paste into Settings -> Deploy keys
   ```

   Then point ssh at it in `~/.ssh/config`:

   ```
   Host github.com
       HostName github.com
       User git
       IdentityFile ~/.ssh/navi_deploy
       IdentitiesOnly yes
   ```
4. Clone this repo to `/srv/navi`, owned by your user rather than root.
5. Restore `.env` from 1Password or the latest state backup, `chmod 600`.
6. `sudo ./scripts/deploy.sh`.
7. Restore `kuma.db` into `/srv/data/uptime-kuma/` if you want the monitors and
   their history back rather than rebuilding eleven monitors by hand.
8. Re-add the two ER605 policy routes for `.61` and `.62` if the router was also
   rebuilt, then check `curl --interface 10.100.100.61 https://api.ipify.org`
   returns the Telmex address.

The state backups are in `/srv/backup` on navi and whatever copy you last pulled
to the laptop. They hold `.env`, `kuma.db`, the blocklist sources, package
selections and the EEPROM config.
