# Deluge with ProtonVPN

Run `playbooks/deluge.yml` from `truenas/`. It deploys only the Deluge custom
app through TrueNAS middleware. Deluge 2.2.0 and Gluetun 3.41.3 images are
version-pinned and use immutable image digests.

Copy `vars.yml.example` to ignored `artifacts/deluge-vars.yml`. Prepare the
config, download, Archive, and VPN datasets first. Deluge uses the configured
media UID/GID. Keep the VPN dataset root-owned with mode `0700` and the
WireGuard file at `VPN_PATH/wg0.conf` with mode `0600`. Never commit this file.

Use a Proton P2P configuration with NAT-PMP enabled. The deployed config uses
IPv4 only; Gluetun's container disables IPv6. Deluge shares Gluetun's network
namespace, and its firewall blocks Internet traffic without the tunnel.
Only the web interface on port 8112 is published to the specified LAN address.
The VPN does not change TrueNAS host routes or the other applications.

Deluge storage mappings:

| Container path | Local host path variable | Purpose |
| --- | --- | --- |
| `/config` | `deluge_config_path` | Credentials, settings, and torrent state |
| `/media` | `deluge_media_path` | Downloads and arr imports |
| `/archive` | `deluge_archive_path` | Local archival torrents only |

The port-sync service reads Proton's NAT-PMP lease and updates Deluge's
advertised listening port over authenticated local RPC. It retries after
either service restarts. The pinned image contains libtorrent 2.0.13, whose
default torrent-file metadata limit rejects an existing 11 MiB torrent.
`metadata-limit.sh` raises the file-loader limit to 32 MiB at startup. It
checks the exact source pattern before editing. Review the fix when changing
the Deluge image, and remove it when upstream exposes an adequate limit.

```sh
ansible-playbook playbooks/deluge.yml -e @artifacts/deluge-vars.yml --check --diff
ansible-playbook playbooks/deluge.yml -e @artifacts/deluge-vars.yml -e truenas_allow_changes=true
```

Repeat the apply and require `changed=0`. Verify the VPN public IP, a download,
port synchronization, and torrent state after an app redeploy. Test that
Internet access fails while only the app's VPN tunnel is stopped, then restore
the tunnel. Verify directory access as the configured media user.

For migration, stop the source daemon and VPN before using the same WireGuard
credential on TrueNAS. Protect and preserve its original config archive and
download data. Rewrite the copied torrent paths to `/media` and retain
`/archive` paths. Restore any rejected torrent with its original file
selection. Disable the source services after validating the new instance.
Keep the source container and original download dataset for rollback.

Enable Deluge's Label plugin. Use separate `sonarr`, `radarr`, `lidarr`, and
`prowlarr` categories and run every arr client's connection test. Preserve
existing SABnzbd clients. Sonarr and Radarr access downloads through a
root-squashed NFS export restricted to their guest addresses. Configure the
`/media/` remote path mapping to their local torrent mount. Lidarr mounts the
same local download dataset at `/media`, so it needs no path mapping.
Do not mount or export Archive to the arr apps.

The deployment playbook does not manage arr API credentials or client settings.
Back up those settings before updating them through each application's API.
Keep API keys and download-client passwords out of logs and command arguments.
