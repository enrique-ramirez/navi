# The box

Raspberry Pi 4 Model B, rev 1.5, 4 GB. Boots from a Kingston A400 480 GB SSD in a UGREEN USB 3.0 enclosure. The 32 GB SanDisk High Endurance microSD stays in the slot as a fallback.

Raspberry Pi OS Trixie (Debian 13), 64-bit, kernel 6.18.39, headless. There's no micro-HDMI cable in the flat, so if SSH ever breaks the recovery path is pulling the card and rewriting it from a laptop. Worth remembering before changing anything that could lock you out.

## Booting

`BOOT_ORDER=0xf14` in the EEPROM. The digits read right to left: `4` is USB, `1` is SD, `f` restarts the sequence. So it prefers the SSD and falls back to the card only if the SSD is missing or unbootable.

The card holds a complete, working system, not a rescue image. If the SSD dies, unplug it and the Pi boots the card.

Both disks carry different PARTUUIDs by construction (`a1b2c3d4` on the SSD, random on the card). This matters: the kernel picks root by PARTUUID, and if both disks claimed the same one it would mount whichever it enumerated first. You'd boot the SSD's kernel onto the card's filesystem, nondeterministically, and spend a very long evening wondering why your changes keep disappearing.

## The SSD enclosure

The listing claimed an ASMedia ASM1153E. It's actually a Realtek `0bda:9201`. Not the JMicron JMS578 that needs a `usb-storage.quirks` kernel parameter, so nothing special is required, and everything needed works: UASP (the kernel binds the `uas` driver), TRIM, and SMART.

SMART needs `-d sat`:

```sh
sudo smartctl -a -d sat /dev/sda
```

Plain `smartctl /dev/sda` fails with "Unknown USB bridge" and returns nothing. Any disk health check that forgets the flag will report success while measuring nothing.

Measured 339 MB/s read, 227 MB/s write, which is about the practical ceiling of the Pi 4's USB 3.0 controller. An 8 GiB random write-verify came back byte-identical, which is what clears a USB bridge of the corruption-under-load failure that makes cheap enclosures dangerous.

## Heat

The Geekworm P173 is a passive aluminium case. It's in the kitchen, which is fine as long as it's nowhere near the hob: airborne grease is bad for a heatsink and worse for a fan.

`stress-ng --cpu 4 --timeout 600s`, run twice: once bare with the lid off and no copper block, once fully assembled with the block and Arctic MX-4.

| | Bare board | Assembled |
|---|---|---|
| Idle | 47.2 °C | **37.9 °C** |
| Peak under load | 83.2 °C | **51.1 °C** |
| Throttled | yes, from ~4 min | **never, 42/42 samples clean** |
| Clock | 1800 → 1677 MHz | **1800 MHz throughout** |
| Under-voltage flags | none | none |

32 °C cooler at peak. Assembled, it runs cooler under a fully saturated CPU than the bare board did sitting idle.

The shape matters as much as the number: temperature flattened at around 90 seconds and drifted up only 5 °C across the following eight minutes. That's a case that's reached equilibrium, not one slowly losing to the load.

This was run with everything live, not on an idle box. DNS, blocking and the landing page all kept working with all four cores pinned, which is worth knowing: Pi-hole needs so little CPU that saturating the machine doesn't touch it.

Re-run it after any hardware change with `scripts/thermal-test.sh`. The header there explains how to wrap it in systemd so it can't outlive its welcome.

No under-voltage flags at full load in either run means the CanaKit 3.5 A supply is comfortably adequate, which rules out the cause of most mysterious Pi corruption.

## HTTPS

Caddy runs its own certificate authority and issues certs for the `.lan` names, so they load with a padlock and count as a secure context. Install steps per platform, the Firefox trust-store trap, and what happens if the CA is ever regenerated are all in [https.md](https.md).

## Access

SSH is key-only. Password authentication is off, root login is off, both set in `/etc/ssh/sshd_config.d/99-hardening.conf`. That file also carries a note on how to recover if you lock yourself out.

`sudo` is passwordless for `enrique`, via `/etc/sudoers.d/010_enrique-nopasswd`. Raspberry Pi OS normally installs that for the first user, but the `userconf.txt` path used for headless setup doesn't. It was validated with `visudo -c -f` before being installed, which you should also do if you ever edit it: a malformed sudoers file locks you out of root on a box with no monitor.

The user password exists only for console recovery. It's in 1Password, and you'll have forgotten it by the time you need it, which is precisely why it's there.

## Docker

Docker CE from Docker's own Debian repo with a pinned GPG key, not `get.docker.com | sh`. Compose v5.

Memory cgroups are enabled via `cgroup_enable=memory cgroup_memory=1` in `cmdline.txt`. Without it Docker can neither report nor enforce per-container memory limits, and `docker stats` shows `0B / 0B`. With it, `mem_limit` in the compose files actually does something, so a runaway container can't take DNS down with it.

`cmdline.txt` must stay a single line. A stray newline makes the Pi unbootable, and there's no monitor in the house to show you the error.

## Updates

`unattended-upgrades` runs daily, restricted to the Debian security pocket.

Raspberry Pi OS ships it wider than you'd expect: the default origins include the general Debian archive, not just security. That line is commented out in `/etc/apt/apt.conf.d/50unattended-upgrades`. Check it with:

```sh
sudo unattended-upgrade --dry-run --debug | grep '^Allowed origins'
```

Kernel and firmware (Raspberry Pi Foundation) and Docker CE are excluded on purpose. A bad kernel on a headless box is a bad afternoon, and upgrading the container engine restarts every container, which drops the flat's DNS. Both stay manual: `sudo apt update && sudo apt full-upgrade`, when you're paying attention.

Automatic reboots are off. This box is the flat's DNS and doesn't get to choose when it disappears. A pending reboot shows up as the `navi · needs attention` monitor instead.
