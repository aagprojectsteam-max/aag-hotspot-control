# Planned v0.3.0 — internationalization component

This component is ready for the planned architectural release. It is not a
publication or acceptance claim for the separate dynamic-uplink work.

- **English is now the default** for fresh installations/user profiles.
- **Full Hebrew RTL remains available**, with IP/MAC/SSID/password values kept LTR.
- Choose **Settings → Language**. The selection applies immediately to the GUI,
  password/device dialogs, diagnostics and tray, without restarting networking.
- Existing users retain Hebrew during upgrade where a trusted legacy GUI
  window-settings file provides evidence of previous use. Explicit saved
  selections always win; no root setting or credential is used for migration.

See [localization](docs/LOCALIZATION.md) for user settings, translation maintenance,
test evidence and safe GUI-only installation. CLI keys and networking behavior
are unchanged by this component. Active-mode language switching is tested with
fixture transport; the production machine remained OFF throughout this task.

The currently published release remains **v0.2.2 Preview**. Its immutable release
notes and assets remain available on the GitHub release page. Do not tag v0.3.0
until the architectural work and its own validation are complete.
