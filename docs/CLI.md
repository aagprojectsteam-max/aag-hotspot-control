# CLI reference

Run as your ordinary user after installation:

| Command | Effect |
| --- | --- |
| `aag-hotspot internet` | Explicitly start/switch to the supported cellular-sharing mode |
| `aag-hotspot local` | Explicitly start/switch to local-only mode |
| `aag-hotspot off` | Idempotently stop/clean the registered AAG session |
| `aag-hotspot status` | Read state and current connected-device keys |
| `aag-hotspot status --json` | Structured state/client snapshot |
| `aag-hotspot doctor` | Read dependencies, route and public state |
| `aag-hotspot doctor --privileged --json` | Authenticate for protected read-only inspection |
| `aag-hotspot configure` | Secure password prompt while OFF; does not activate |
| `aag-hotspot internet --dry-run --json` | Describe the action only; no runtime-preflight claim |

Text status preserves existing keys and adds `CLIENT_COUNT` plus numbered MAC,
IPv4, hostname, signal dBm and connected-seconds keys. JSON preserves `clients`
and provides `client_count`, `client_details`, `client_data_status` and capture time.
Unknown values remain unknown/null, rather than being invented or indefinitely cached.

Status/doctor do not disclose the hotspot password. Their networking identifiers
can still be private; redact before posting an issue. A failed action or unknown
health returns nonzero. Inspect the error and use OFF for scoped recovery; never
stop NetworkManager globally or flush firewalls as an AAG recovery shortcut.
