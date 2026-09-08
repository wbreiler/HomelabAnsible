# Lidarr

The dedicated `playbooks/lidarr.yml` deploys a TrueNAS custom application using
LinuxServer Lidarr `3.1.0.4875-ls38`. It reconciles only Lidarr and its two
dedicated directories, using the supported middleware API.

Copy `files/lidarr/vars.yml.example` to ignored `artifacts/lidarr-vars.yml` and
set existing storage parent paths, the media account IDs, and a LAN bind address.
The playbook creates ordinary directories, not datasets. Downloads are mounted
at `/nzb` to match SABnzbd; the music library is mounted at `/music`.

From `truenas/`, after read-only discovery and a fresh protected configuration
backup as described in the project README:

```sh
ansible-playbook playbooks/lidarr.yml --check --diff -e @artifacts/lidarr-vars.yml
ansible-playbook playbooks/lidarr.yml -e @artifacts/lidarr-vars.yml -e truenas_allow_changes=true
```

Repeat the apply and require `changed=0`. Open port 8686 at the configured LAN
address, complete authentication setup, and configure the `/music` root,
download client, and music indexers. Keep API keys out of tracked files and
command arguments. App settings persist in `/config`; the deployment playbook
does not replace the Lidarr database or manage its internal settings.

Validate artist lookup through Lidarr, the download client's connection test,
directory access as the media user, and app/storage health. Successful metadata
lookups do not establish complete catalog coverage: upstream still advertises
metadata cache recovery. Download/import verification needs a configured indexer
and a user-selected release.

Upstream references:

- https://github.com/Lidarr/Lidarr
- https://docs.linuxserver.io/images/docker-lidarr/
