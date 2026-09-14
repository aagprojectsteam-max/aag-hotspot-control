# Configuration and private data

Use the GUI password menu or `aag-hotspot configure` while OFF. The password is
stored root-owned 0600 at `/var/lib/aag-hotspot/credentials.json`, never in this
repository. There is no secret command argument or retrieval API.

The installer records a validated nonsecret radio/profile binding in root-owned
0644 `/usr/lib/aag-hotspot/host.json`, protected by the package receipt. It contains
local identifiers and must not be published. Update preserves it; explicit
`sudo ./install.sh --rebind` while OFF refreshes the binding from read-only local
state. No arbitrary uplink, shell, firewall or modem setting is accepted.

SSID AAG-Hotspot, subnet 10.77.0.0/24 and channel 6 remain fixed. Wi-Fi uplink is
disabled. User geometry under the XDG config directory contains dimensions only.
