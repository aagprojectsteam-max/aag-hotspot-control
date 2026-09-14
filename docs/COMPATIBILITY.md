# Compatibility and installation gates

Only Ubuntu 26.04 x86_64 with GNOME/GTK4/Libadwaita and NetworkManager 1.54 has
host-side evidence. The cellular implementation expects an existing GSM profile on
`wwan0mbim0` and public/default IPv4 routing through `wwan0`; FM350 is the exercised
modem. Other modem device layouts and Internet uplinks are not enabled.

Wi-Fi must advertise AP support and virtual-interface combinations. Channel 6
(2437 MHz) must be legal in the current regulatory state. The backend uses a
separate AAG-owned AP interface; it does not convert or disconnect a saved Wi-Fi
station. Same-radio Wi-Fi STA+AP Internet uplink is disabled.

Installation selects the sole existing managed Wi-Fi interface, or the explicit
`--wifi-interface` selection when several exist. It reads the radio index, active
supported cellular profile and any saved profiles named Hotspot. It stores these
nonsecret bindings in root-owned 0644 `/usr/lib/aag-hotspot/host.json`, covered by
the installation receipt. Do not publish that file: it contains local identifiers.
No real host binding is shipped in the archive or committed to Git.

Bindings are preserved on update. Changing the cellular profile/radio deliberately
requires OFF and `sudo ./install.sh --rebind`. If no supported cellular connection
is active at installation, local-only mode remains available; Internet mode needs
a later explicit rebind after the connection is established outside AAG.

The current validated firewall arrangement is NetworkManager's **iptables** backend,
with the nft-compatible iptables implementation and global IPv4 forwarding already
set to 1. The AAG installer refuses incompatible prerequisites. It does not write
`sysctl.conf`, enable forwarding, change NetworkManager configuration or flush rules.
If your clean installation differs, do not apply global firewall changes just to
silence a check; use a separate test machine and request support with sanitized
versions/configuration facts. General clean-Ubuntu compatibility is not claimed.

Existing Docker/Tailscale configurations were preserved during development-host
validation. This is not a guarantee that every VPN/firewall permits downstream
client traffic. A guard accept does not override a drop in another owner's chain.
AAG refuses route/subnet conflicts and never rewrites those owners' policies.

Preview status: physical-client Internet and BeeBEEP acceptance are incomplete.
The publication-specific binding layer is tested using mocks and staged files;
no live radio activation is part of publication or CI.
