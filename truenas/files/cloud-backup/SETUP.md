# IDrive e2 backups

## Configured and tested — 2026-10-22

TrueNAS 25.10.4 supports generic S3 through its native Cloud Backup API.
This deployment uses the bundled restic 0.16.4, the Virginia endpoint
`https://s3.us-east-1.idrivee2.com`, and the separate `truenas-backup` bucket.
No additional container or package was installed.

All production tasks remain **disabled**. Their candidate schedule is 04:00
in the TrueNAS host timezone. Do not start an initial production backup or
activate a schedule without approval. Running the configuration playbook
leaves these tasks disabled deliberately.

## Backup scopes

Each scope has a separate encrypted repository prefix. Native Cloud Backup
runs `forget --keep-last 30 --group-by '' --prune` after a successful backup.
Separate repositories prevent one scope's retention from removing another
scope's snapshots. Approve this retention policy before production runs.

| Scope | Source | Consistency |
| --- | --- | --- |
| Archive | `/mnt/gaia/Archive`, excluding `YouTube` | File backup; nested dataset prevents native snapshot mode |
| Clips | `/mnt/gaia/clips` | Temporary native ZFS snapshot |
| Time Machine | `/mnt/gaia/TimeMachine/MacBook-Pro` | Temporary native ZFS snapshot |
| Application data | `/mnt/gaia/appdata` | Consistent SQLite copies plus ordinary application files |
| Application settings | `/mnt/gaia/backups/truenas-app-settings` | Protected export from the hidden app-config mount |
| System configuration | `/mnt/gaia/backups/truenas-config` | Supported configuration export with secret seed, pool keys, and root authorized keys |

The last two scopes use pre-scripts to refresh their exports before backup.
The current application settings export is under `configs/`. The preliminary
export at the directory root remains as an additional recovery copy.

No media, downloads, ISO, model, or YouTube source is included. Appdata excludes
LANCache, Ollama, standalone tool downloads, the Tdarr transcode cache, and
backup caches/test directories. Native backup paths are relative to the task
source. **Do not prepend `/` to these exclusion patterns**: the restore test
proved that leading-slash patterns did not exclude the synthetic files.

## Application databases

The pre-script copies SQLite `.db`, `.sqlite`, and `.sqlite3` files through the
SQLite backup API, including committed WAL transactions. It validates each
copy and converts it into a standalone database. Copies live under
`/mnt/gaia/appdata/_cloud-backup/sqlite`, with the original relative paths.
These copies, rather than potentially changing raw databases, are the
preferred sources for database restore. Raw application files are retained too.

Plex databases require its ICU collation. For these copies, the helper uses
Plex's own SQLite binary in `ix-plex-plex-1` to validate a protected temporary
copy. It removes that temporary container file afterward. It does not restart
or reconfigure Plex. A missing container/tool or failed integrity check aborts
the preparation rather than silently accepting an unverified copy.

The production preparation check successfully copied and validated 15 SQLite
databases. The automated unit check covers an open WAL database, excluded cache
folders, symlinks, non-SQLite files, and restrictive destination permissions.
Non-SQLite application state does not gain application-level transaction
consistency from this helper. Archive files are not a simultaneous ZFS image.

## Restore test

The native validation task is disabled and uses its own `validation` repository
prefix. A synthetic fixture contains a 32 MiB random file, an Archive text file,
an empty file, a SQLite database, and its consistent database copy.

The encrypted backup and native restore passed:

- All five expected files matched their original SHA-256 hashes.
- YouTube, LANCache, Tdarr transcode cache, and backup cache files were absent.
- The restored consistent database returned the expected SQL record.
- All six production tasks remained disabled, and no production snapshot ran.

Test state is in `/mnt/gaia/appdata/_cloud-backup/test-result.json`. Synthetic
files and restored fixtures remain in the excluded test directories. An early
validation snapshot includes synthetic excluded files from the failed exclusion
check; no real YouTube or cache data was uploaded. The corrected latest snapshot
passed the exclusion checks. Do not infer historical test content from current
exclusion settings.

## Secrets and recovery

The credentials and generated repository password are stored in the ignored,
Ansible-Vault-encrypted artifact:

`truenas/artifacts/cloud-backup-secrets-2026-10-22.vault`

It uses the existing Kuma vault password at
`~/.config/ansible/vault-passwords/kuma`. Preserve this encrypted artifact and
that password outside TrueNAS. The restic password is separate from the PBS
encryption key. Losing it prevents cloud restore.

Before the first configuration change, a supported configuration export was
saved as `truenas/artifacts/erebus-config-before-cloud-2026-10-22.tar.vault` on
the controller. Its secret material never entered Git or process arguments.
Live exports and helper working files use protected directories on TrueNAS.

## Reapply configuration

From `truenas/`, first perform a check:

```sh
ANSIBLE_LOCAL_TEMP=/tmp/ansible-truenas-local \
ANSIBLE_REMOTE_TEMP=/tmp/ansible-truenas-remote \
ansible-playbook playbooks/cloud-backup.yml --check --diff \
  --vault-password-file ~/.config/ansible/vault-passwords/kuma \
  -e @artifacts/cloud-backup-secrets-2026-10-22.vault
```

Apply only this playbook with `-e truenas_allow_changes=true`, then repeat it to
verify `changed=0`. It uses the supported local JSON-RPC client over SSH.
Credentials travel through protected standard input, never command arguments.

Before an initial production run, obtain explicit approval for native temporary
snapshot creation and automatic cleanup on **`gaia/clips`** and
**`gaia/TimeMachine/MacBook-Pro`**, plus the cloud retention policy. The appliance
rules require approval for snapshot deletions. No pool, dataset, ACL, network,
SSH service, or account configuration changes are part of this deployment.
