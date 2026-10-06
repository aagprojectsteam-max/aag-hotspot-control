# v0.3.0 Preview candidate — dynamic uplink and languages

Publication is gated on completed installed live validation. No v0.3.0 tag or release
has been published by this candidate work yet.

- Kernel-route-selected Cellular and physical Ethernet, classified through authoritative
  NetworkManager metadata. No cellular UUID, provider or fixed WWAN device requirement.
- Dynamic scoped forwarding; private upstream routers supported, unrelated Docker,
  Tailscale and ZeroTier interfaces protected.
- Local-only mode works without an Internet route or connected uplink, with IPv4,
  IPv6 and DNS isolation retained.
- Wi-Fi STA+AP capability and same-channel planning implemented. Production Wi-Fi
  remains UNVALIDATED_DISABLED until safe live coexistence evidence is available.
- GUI, status and doctor report the detected source; CLI machine keys remain stable.
- English is the default for new profiles. Full Hebrew RTL remains available in
  Settings → Language, with immediate switching and safe legacy-user migration.
- Scoped password reveal/copy, connected-device visibility, minimal tray and the
  existing readiness/ownership/cleanup protections are preserved.

Live Ethernet and physical-client acceptance are not claimed by mocked or isolated
network-namespace tests. The current installed/live result and any blockers must be
recorded before this candidate becomes a public preview release.
