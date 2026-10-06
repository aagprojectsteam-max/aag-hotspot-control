# Compatibility and installation gates

Only Ubuntu 26.04 x86_64 with GNOME/GTK4/Libadwaita and NetworkManager 1.54 has
host-side evidence from earlier previews. v0.3.0 selects Cellular and physical
Ethernet through kernel routes and NetworkManager metadata, independent of device
name, provider or profile UUID. The new installed live acceptance is pending.
Live Ethernet is not claimed without an active Ethernet uplink to test.

Wi-Fi must advertise AP support and virtual-interface combinations. The normal
idle-radio path uses legal 2.4 GHz channel 6. A separate AAG-owned virtual interface
preserves the existing user Hotspot profile and saved Wi-Fi profiles. Another active
AP/STA is preserved and blocks this path. STA+AP capability and same-channel planning
are implemented, but production Wi-Fi uplink is UNVALIDATED_DISABLED.

Installation selects the existing Wi-Fi radio or an explicit `--wifi-interface`
selection. Root-owned mode-0644 `/usr/lib/aag-hotspot/host.json` stores only schema 2,
Wi-Fi interface and wiphy. Old schema-1 uplink/profile identities are discarded on
upgrade. No local binding is shipped in the archive. Recreated cellular profiles
never require rebind; `--rebind` applies only to a deliberate AP-radio change.
Local-only works without any Internet uplink.

The current validated firewall arrangement is NetworkManager's **iptables** backend,
with the nft-compatible iptables implementation and global IPv4 forwarding already
set to 1. The AAG installer refuses incompatible prerequisites. It does not write
`sysctl.conf`, enable forwarding, change NetworkManager configuration or flush rules.
If your clean installation differs, do not apply global firewall changes just to
silence a check; use a separate test machine and request support with sanitized
versions/configuration facts. General clean-Ubuntu compatibility is not claimed.

Existing Docker/Tailscale/ZeroTier configurations were preserved during development-host
validation. This is not a guarantee that every VPN/firewall permits downstream
client traffic. A guard accept does not override a drop in another owner's chain.
AAG refuses route/subnet conflicts and never rewrites those owners' policies.

Preview status: physical-client Internet and BeeBEEP acceptance are incomplete.
The publication-specific binding layer is tested using mocks and staged files;
CI never activates radios. An installed controlled live run is required before publishing v0.3.0.
