# v0.2.2 — authenticated password reveal

View or copy the configured Wi-Fi password from the Hebrew GUI in OFF, Internet,
or Local-only mode. The secondary **הצג סיסמה** action uses the existing scoped
Polkit helper. Revealing a password does not restart or disconnect the hotspot.

The dialog begins masked, hides visible text after 30 seconds, clears its owned
clipboard after 30 seconds or closing, and expires after 60 seconds. Authorization
failure leaves networking untouched. Credentials stay root-owned 0600; the GUI
stays unprivileged. No changes to network lifecycle, firewall policy, or Wi-Fi
uplink support are included.

See [password reveal and update instructions](docs/PASSWORD_REVEAL.md). Existing
compatible installations can use the five-file transactional updater; new installs
follow the normal [installation guide](README.md#installation).

This remains a hardware-dependent public preview. Wi-Fi STA+AP is disabled.
Physical-client and BeeBEEP acceptance is not implied by GUI or host-side tests.
Checksums and a per-file release manifest accompany the source archive; artifacts
are not cryptographically signed. Only sanitized public history is published.
