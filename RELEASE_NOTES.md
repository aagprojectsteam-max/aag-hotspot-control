# AAG Hotspot Control v0.2.1 — public preview

This patch corrects the optional compatibility-check command: run
`sudo ./install.sh --check` to inspect protected NetworkManager configuration.
Inspection remains read-only. The installer already required administrator access.

A native Ubuntu/GNOME Wi-Fi hotspot controller with Internet sharing, local-only
LAN mode, connected-device visibility and a Hebrew RTL interface.

Features include cellular Internet sharing over the supported `wwan0` path,
local IPv4/IPv6 forwarding isolation, a stable GTK4/Libadwaita window, a dedicated
client page, symbolic tray integration, independent CLI/diagnostics, a scoped
Polkit helper, bounded readiness and ownership-checked cleanup.

Tested host-side architecture: Ubuntu 26.04 x86_64, GNOME, NetworkManager 1.54,
Intel AP-capable Wi-Fi and FM350 cellular. Installation checks the compatibility
requirements and records nonsecret machine bindings locally; it never activates
hotspot or enables autostart. Public binding/packaging changes passed mock/staging
tests; they have not undergone a separate live external-machine activation.

**Limitations:** Hebrew GUI only. Same-radio Wi-Fi STA+AP uplink is disabled.
Full physical-client Internet/reachability and BeeBEEP acceptance are NOT_TESTED.
Do not treat this preview as a universal Linux/hardware compatibility claim.

Download the archive, SHA256SUMS and release-manifest.json together. Verify with
`sha256sum --check SHA256SUMS`, extract, read README requirements and run
`sudo ./install.sh`. Removal is `sudo ./uninstall.sh` from the extracted directory.
Credentials and unrelated network configuration are preserved by default.

The checksum file verifies artifact integrity, not independent author identity;
this release is not cryptographically signed. Source history starts from a fresh
sanitized publication root; private development evidence is not included.
