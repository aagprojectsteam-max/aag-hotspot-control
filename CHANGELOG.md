# Changelog

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
