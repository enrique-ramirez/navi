# HTTPS on the LAN

Services here answer on both `http://` and `https://`. The certificates come from
Caddy, which runs its own certificate authority on navi. Install its root on a
device once and every `.lan` name loads with a padlock and no warning.

## Why bother

Browsers gate a set of APIs behind what they call a secure context, and plain HTTP
isn't one. `localhost` counts. A LAN address doesn't, and neither does a `.lan`
name, no matter how much you trust your own network.

The one that matters here is `navigator.mediaSession`. It's what puts track title,
artist and artwork on a phone's lock screen and makes the hardware media keys
work. Over HTTP the property doesn't exist at all. Jean can't implement it, and no
amount of clever code gets around that.

`Notification` is the same story, and service workers (so, installable PWAs) are
too.

None of this is about eavesdropping. Nobody's sniffing your flat. It's about
browsers refusing to hand a page certain capabilities unless the origin is
secure, and that refusal is absolute.

## The shape of it

Every service is served twice, on both schemes, from the same Caddyfile. That's
deliberate.

Devices that can trust the CA get HTTPS and everything that comes with it. Devices
that can't (smart TVs, consoles, a guest's laptop) keep working over plain HTTP
exactly as before. There's no redirect from one to the other, because a redirect
would break the second group.

`auto_https disable_redirects` in the global block is what keeps Caddy from
helpfully adding those redirects.

## music.lan is the exception

It's HTTPS-only, and it has to be.

A single port can't serve both HTTP and HTTPS. Jean derives foo_jean's address
from `window.location`, so the page and the component on port 8881 always share a
scheme. If 8881 were plain and the page were TLS, the browser would block it as
mixed content. If 8881 were TLS and the page plain, the connection would be
refused. Either way Jean reports NOT CONNECTED, streaming disappears, and nothing
on screen says why.

Half-working was the worse option, so `http://music.lan` redirects to HTTPS. A
device without the root installed gets an honest certificate warning rather than a
service that looks fine and isn't.

If you need Jean somewhere you can't install the CA, go straight to the player at
`http://10.100.100.20:8880/jean` and skip Caddy entirely.

## The certificates

Leaf certificates last **12 hours** and renew themselves. That's Caddy's design,
and it means a leaked leaf is worthless almost immediately. The root lasts until
2036.

```
root on navi   /srv/data/caddy/caddy/pki/authorities/local/root.crt
in this repo   www/navi-root.crt
download       http://help.lan/navi-root.crt
SHA-256        97:34:12:56:8C:A2:F7:3D:E2:3E:72:31:57:0A:44:30:6D:9B:44:70:D9:E4:19:30:EE:07:81:74:12:86:81:E1
```

Check that fingerprint before you trust the file anywhere. Installing a root CA
gives it permission to impersonate any website to that device, which is exactly as
serious as it sounds, and the check takes ten seconds:

```sh
openssl x509 -in navi-root.crt -noout -fingerprint -sha256
```

The certificate itself is public and safe to commit. The private key stays in
`/srv/data/caddy` on navi and never leaves it.

## Installing it

**macOS**

```sh
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain navi-root.crt
```

Safari and Chrome pick it up immediately. Zen and Firefox won't, see below.

**iOS and iPadOS.** Download it in Safari, then Settings → Profile Downloaded →
Install. That isn't enough on its own. Also go to Settings → General → About →
Certificate Trust Settings and switch it on there. Missing that second step is the
usual reason someone thinks the certificate didn't work.

**Android.** Settings → Security → Encryption & credentials → Install a
certificate → CA certificate. Browsers honour it. Native apps don't, because since
Android 7 apps ignore user-installed CAs unless they opt in.

**Windows.** Double-click, Install Certificate, Local Machine, and place it in
Trusted Root Certification Authorities.

**Smart TVs and consoles need nothing.** Secure context is a browser rule and
native apps aren't bound by it. A Jellyfin TV app talking to plain HTTP works and
always will. Tizen and webOS don't expose a user certificate store anyway, so this
was never going to be an option there.

## Firefox keeps its own trust store

This one wastes an hour if you don't know it.

Firefox, Zen and LibreWolf don't use the macOS keychain or the Windows certificate
store. They have their own, and a root installed system-wide does nothing for
them. Refreshing won't help. Safari and Chrome will be working at that point,
which makes it look like one site is broken rather than one browser.

Import it directly: Settings → Privacy & Security → Certificates → View
Certificates → Authorities → Import, and tick "Trust this CA to identify
websites".

The alternative is `about:config`, set `security.enterprise_roots.enabled` to
`true`, then fully quit and reopen the browser. Firefox reads system roots once at
startup, so restarting isn't optional. The direct import is more reliable.

Quickest way to tell the two apart: if a name loads cleanly in Safari and warns in
Zen, the certificate is fine and the browser is the problem.

## The router is a special case

`router.lan` and `gate.lan` point at navi, not at the ER605, and Caddy proxies
them through.

The router answers on 443 with a certificate TP-Link generated in a factory in
2018. Browsers that auto-upgrade to HTTPS find it and throw a full-page warning
every time. Behind the proxy they see a certificate from navi's CA instead.

Caddy talks to the router over plain HTTP. Proxying to its HTTPS fails with
`remote error: tls: handshake failure`, because the ER605 only offers cipher
suites that Go's TLS client won't accept, and Caddy exposes no way to negotiate
down. `curl` connects to it happily, which makes the failure look stranger than it
is.

So that hop is cleartext, one switched hop on the same wire. It's what already
happened when you browsed to the router directly, and the browser-to-navi half is
now encrypted, so there's less plaintext than before rather than more.

`https://10.100.100.1` always works directly, which is what you want when navi is
the thing that's broken.

## If Jean becomes a native app

This decides which approach you'd need, so it's worth knowing before you pick a
wrapper.

A WebView build (Capacitor, Cordova, a hand-rolled Android WebView) can bundle
this CA in its network security config and trust it for `.lan` only, without
depending on the phone's user certificate store at all:

```xml
<network-security-config>
  <domain-config>
    <domain includeSubdomains="true">lan</domain>
    <trust-anchors>
      <certificates src="@raw/navi_ca"/>
    </trust-anchors>
  </domain-config>
</network-security-config>
```

A Trusted Web Activity can't. TWA runs the page in real Chrome and requires a
publicly trusted certificate plus Digital Asset Links verification against a
domain you own. Going that route means Let's Encrypt with DNS-01 and names like
`music.h.enrique-ramirez.com` instead of `music.lan`, which is why we didn't start
there.

## Regenerating the CA

Delete `/srv/data/caddy/caddy/pki` and Caddy builds a new authority on next start.
Every device then has to install the new root, and the old one should be removed
from each of them.

Don't do this casually. There's no upgrade path that keeps existing devices
working.
