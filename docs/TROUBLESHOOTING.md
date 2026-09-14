# Troubleshooting

Start with `aag-hotspot status` and `aag-hotspot doctor`. These are read-only. Review
and redact IP/MAC/hostname/UUID fields before sharing them. Do not attach complete
NetworkManager profiles, credentials, journals or firewall dumps.

## Installation refused

`./install.sh --check` describes the first unsupported prerequisite without writing
files. Check Ubuntu/architecture, NetworkManager 1.54, GTK4/Libadwaita, AP support,
channel legality, current NM iptables backend and pre-existing forwarding=1.
The installer preserves global networking. Read [compatibility](COMPATIBILITY.md)
for the deliberately limited preview scope; do not assume a missing dependency is
the same as missing hardware support.

## Radio or readiness failure

Check airplane mode, physical radio switches and `rfkill list`. An active Wi-Fi
station is preserved, and STA+AP is disabled. The app waits for its own device to
reach an activation-capable managed state for a bounded interval. On timeout it
uses ownership-checked cleanup. Do not rename interfaces or start retry loops.

## Internet mode refused or no client Internet

The supported cellular connection must already be active on `wwan0mbim0`; the
public/default IPv4 route must be `wwan0`. A changed cellular connection UUID needs
an explicit OFF/install `--rebind`. The app does not connect/reconfigure the modem.
VPN default routing, CGNAT/private destinations, subnet conflicts, client firewall
or another host firewall's forwarding drops can explain blocked traffic. AAG does
not override Docker/Tailscale or other owners' rules. External-client validation
is separate from DHCP/NAT infrastructure checks.

## Missing client or changed address

Only active station association establishes a connected client. A stale DHCP lease
or neighbor entry does not. Wait for refresh, ensure the device uses AAG-Hotspot,
and read its current address. Reconnects and mode changes can assign another IP.
Unknown hostname is normal when a client supplies none; missing DHCP can leave the
station visible with no known IPv4. Copy IP uses only current, unexpired data.

## Tray or window

The GUI is Hebrew RTL; IP/MAC fields are LTR. On Ubuntu's tray host a single click
opens a minimal menu and double-click opens the window. If no compatible host is
registered, use the main window; optionally install/enable the AppIndicator extension.
No extension or autostart is enabled by the installer. Reset a corrupt window size
by removing only the per-user `aag-hotspot/window.json` preferences file while the
GUI is closed. Do not remove system runtime/credential files.

## OFF/removal fails

Run `aag-hotspot off` and inspect its controlled error. Unknown ownership, a changed
profile/interface/table or failed NM cleanup must be reviewed before removal.
Uninstall keeps its helper and files if cleanup fails. Never use a global firewall
flush, delete profiles by prefix, stop NetworkManager, reboot or modify modem/GNSS
settings as a scripted workaround. Report the sanitized failure and release version.
