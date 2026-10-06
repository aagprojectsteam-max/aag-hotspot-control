# v0.3.0 Preview candidate — dynamic uplink and languages

Host-side installed live validation passed for Local-only and dynamically detected
Cellular Internet on the documented Ubuntu 26.04 system. This release remains a
preview because Ethernet has no live hardware acceptance, same-radio Wi-Fi STA+AP
remains disabled, and physical-client/BeeBEEP acceptance is still pending.

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

The final live run verified Local-only and Cellular Internet activation, DHCP/DNS/NAT
infrastructure, dynamic guard policy, password reveal/copy, English/Hebrew switching
while active, mode transitions, final OFF cleanup, and protected-state restoration.
No client was associated during that run. Live Ethernet, physical-client/BeeBEEP,
and Wi-Fi STA+AP acceptance are therefore not claimed.
