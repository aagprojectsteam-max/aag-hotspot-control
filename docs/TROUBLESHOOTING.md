# Troubleshooting

Start with `aag-hotspot status` and `aag-hotspot doctor`. These are read-only. Review
and redact IP/MAC/hostname/UUID fields before sharing them. Do not attach complete
NetworkManager profiles, credentials, journals or firewall dumps.

## Installation refused

`sudo ./install.sh --check` describes the first unsupported prerequisite without writing
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

Inspect `UPLINK_TYPE`, `UPLINK_INTERFACE`, `UPLINK_DEVICE`, `UPLINK_SUPPORTED` and
`UPLINK_REASON` in status, and the selected public route in doctor. Cellular and
physical Ethernet are selected dynamically; no rebind is needed after a cellular
UUID/provider change. The app never connects or configures the modem itself.

An unsupported VPN/virtual selected route, split public paths, subnet conflict,
client firewall or another owner's forwarding drop can prevent sharing. No silent
fallback or global firewall repair is attempted. Private upstream router addresses
are supported on the selected physical uplink. A changed active route causes safe
AAG shutdown; start Internet mode again to select the new path. Local-only needs no
Internet route or connected uplink. Physical-client traffic remains a separate
acceptance test from host DHCP/NAT infrastructure.

## Missing client or changed address

Only active station association establishes a connected client. A stale DHCP lease
or neighbor entry does not. Wait for refresh, ensure the device uses AAG-Hotspot,
and read its current address. Reconnects and mode changes can assign another IP.
Unknown hostname is normal when a client supplies none; missing DHCP can leave the
station visible with no known IPv4. Copy IP uses only current, unexpired data.

## Tray or window

The GUI supports English LTR and Hebrew RTL; IP/MAC fields stay LTR. Settings → Language switches immediately. On Ubuntu's tray host a single click
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
