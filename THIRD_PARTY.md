# Third-party components and provenance

The archive contains original AAG application code, original symbolic SVG assets,
project tests and documentation. It does not vendor Python, GTK, Libadwaita,
NetworkManager, nftables, iptables, dnsmasq, Polkit, systemd or GNOME extensions.
Those are installed as Ubuntu packages and retain their upstream licenses/notices.
No rights in those projects are claimed by AAG's MIT license.

Primary upstream projects:

- [GTK](https://gitlab.gnome.org/GNOME/gtk) and [Libadwaita](https://gitlab.gnome.org/GNOME/libadwaita).
- [PyGObject](https://gitlab.gnome.org/GNOME/pygobject) and [Python](https://www.python.org/).
- [NetworkManager](https://networkmanager.dev/), [nftables](https://netfilter.org/projects/nftables/) and [iptables](https://netfilter.org/projects/iptables/).
- [dnsmasq](https://thekelleys.org.uk/dnsmasq/doc.html), [Polkit](https://gitlab.freedesktop.org/polkit/polkit) and [systemd](https://systemd.io/).
- [Ubuntu AppIndicator extension](https://github.com/ubuntu/gnome-shell-extension-appindicator).

The tray implements the public StatusNotifierItem/DBusMenu protocol; no GNOME
extension implementation is bundled. Screenshots show project widgets and synthetic
data. CI downloads checksum-pinned Gitleaks and uses distribution ShellCheck;
neither binary is included in the application release archive.

The previous local LICENSE file was empty. The first public release supplies the
MIT license for original project material, using the standard license text from
[GitHub Choose a License](https://choosealicense.com/licenses/mit/).
