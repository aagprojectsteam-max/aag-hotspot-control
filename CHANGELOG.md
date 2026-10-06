# Changelog

## 0.3.0 Preview — 2026-10-06 — dynamic uplink and languages

- Host-side live acceptance passed for Local-only and dynamically detected Cellular Internet on Ubuntu 26.04.
- The final live run verified DHCP/DNS/NAT infrastructure, dynamic guard policy, password reveal, bilingual runtime switching, bounded mode transitions, final OFF cleanup and protected-state restoration.
- The current cellular profile was accepted despite a changed NetworkManager UUID, confirming removal of machine-specific cellular identity.
- Ethernet remains hardware-unvalidated; same-radio Wi-Fi STA+AP remains UNVALIDATED_DISABLED; physical-client/BeeBEEP acceptance remains pending.
- English is the default language for fresh user profiles.
- Hebrew remains available with full RTL layout and LTR technical values.
- Settings → Language applies changes immediately to the GUI and tray without
  restarting the hotspot or backend.
- Existing Hebrew users are migrated once when trusted legacy GUI settings are
  present; explicit per-user language choices always win.
- English source strings and maintained Hebrew gettext catalogs support future
  languages without separate GUI implementations.
- This component does not change uplink detection, firewall policy, CLI machine
  keys, or the current Wi-Fi STA+AP validation boundary.

- Kernel-selected dynamic Cellular/Ethernet uplink classification using NetworkManager metadata.
- No cellular UUID/provider/device binding; schema-2 installation binds only the AP radio.
- Dynamic egress guard and RFC1918 upstream support with protected-interface isolation.
- Local-only operation independent of Internet routes and connected uplinks.
- Gated STA+AP capability/channel architecture; Wi-Fi remains unvalidated and disabled.
- Dynamic GUI/status/doctor source reporting, bounded route-change cleanup and expanded tests.

## 0.2.2 — 2026-10-06 — password reveal

- Add an explicit Hebrew password-reveal action beside network information in OFF, Internet and Local modes.
- Read credentials through the fixed authenticated helper without invoking networking or restarting the hotspot.
- Start masked; hide visible text and clear the owned clipboard after 30 seconds; close and clear the dialog after 60 seconds.
- Preserve root-owned 0600 credentials, unprivileged GUI, status/doctor output and the existing network controller.
- Add secret-safe failure tests, real GTK/clipboard checks and a narrowly scoped transactional updater.

## 0.2.1 — 2026-09-14 — public preview correction

- Require administrator execution for system compatibility inspection because
  NetworkManager's effective configuration can be protected.
- Correct the read-only check command to `sudo ./install.sh --check`; inspection
  still creates no files or network state.
- Retain immutable 0.2.0 history/tag; no network policy or activation changes.

## 0.2.0 — 2026-09-14 — first public preview

- Internet-sharing and local-only hotspot modes with an idempotent OFF path.
- NetworkManager AP/shared-mode integration and scoped nftables IPv4/IPv6 isolation.
- Fixed Polkit helper, bounded readiness, operation locking and ownership-checked cleanup.
- Hebrew RTL GTK4/Libadwaita interface with state-specific controls, saved geometry,
  separate connected devices and a minimal symbolic tray indicator.
- Authoritative associated-client MAC, DHCP/neighbor address join, signal/time and
  stale-snapshot expiry exposed through the GUI and independent CLI.
- Public installation/removal wrappers, read-only environment checks and local
  hardware/profile binding instead of developer machine identifiers.
- Public documentation, MIT licensing, issue templates, hardware-free CI,
  sanitized source history and reproducible release archives/checksums.

This preview retains the existing 0.2.0 product version. Host-side cellular/local
architecture was previously exercised on the documented development configuration.
Public binding/packaging changes are mock/staging validated only. Physical-client
and BeeBEEP acceptance remain pending; Wi-Fi STA+AP uplink is disabled.
