# IDrive e2 backups

[Restore and disaster recovery guide](RESTORE.md)

## Configured and tested — 2026-10-22

TrueNAS 25.10.4 supports generic S3 through its native Cloud Backup API.
This deployment uses the bundled restic 0.16.4, the Virginia endpoint
`https://s3.us-east-1.idrivee2.com`, and the separate `truenas-backup` bucket.
No additional container or package was installed.

The user approved the initial upload, 30 versions per scope, temporary
snapshot creation/cleanup, nightly backups after initial success, and Discord
completion notifications. The initial upload started on 2026-10-22 at 21:34
America/Chicago under `truenas-e2-initial-backup.service`.

Per-scope native task schedules remain **disabled by design**. A sequential
runner invokes them through the supported API. After every initial scope
succeeds, the runner creates one native TrueNAS cron job named
**IDrive e2 nightly backups** at **04:00 America/Chicago**. It sends a Discord
completion notification. If any scope fails, it stops and does not activate
the nightly job. It sends a failure notification instead.

The native cron entry, rather than each task's Enabled checkbox, controls
nightly execution. Reapplying the configuration playbook leaves the native
per-scope schedulers disabled and does not modify the sequential cron job.

## Backup scopes

Each scope has a separate encrypted repository prefix. Native Cloud Backup
runs `forget --keep-last 30 --group-by '' --prune` after a successful backup.
Separate repositories prevent one scope's retention from removing another
scope's snapshots. The user explicitly approved this retention policy.

| Scope | Source | Consistency |
| --- | --- | --- |
| Archive | `/mnt/gaia/Archive`, excluding `YouTube` | File backup; nested dataset prevents native snapshot mode |
| Clips | `/mnt/gaia/clips` | Temporary native ZFS snapshot |
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
- During the validation test, all production schedules remained disabled and
  no production snapshot ran.

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

The user explicitly approved native temporary snapshot creation and automatic
cleanup on **`gaia/clips`** and **`gaia/TimeMachine/MacBook-Pro`**, plus 30 versions
per cloud scope. This approval covers the configured backup workflow. No pool,
dataset, ACL, network, SSH service, or account configuration changes are part
of this deployment.

Time Machine is excluded at the user's request after its initial snapshot failed.
Its existing native task remains disabled and is not called by the runner.
Clips retains native snapshot mode without a `.zfs` exclusion, because that
pattern matches the snapshot source itself and produces an empty backup.

## Sequential runner and notifications

`run.py` uses a nonblocking lock to prevent overlapping runs. It validates the
five repository prefixes, retention, disabled per-scope schedules, and Archive's
YouTube exclusion before starting any scope. The order is system configuration,
application settings, application data, clips, then Archive.
Each scope must finish before the next starts. It waits for multi-hour native
jobs without a short client timeout.

The success-gated schedule logic has automated checks for both complete
success and a failed intermediate scope. A live Discord test delivered
successfully using the same destination as Proxmox/PBS. The webhook is stored
in the encrypted controller vault artifact and in root-only `discord.json`
on TrueNAS. It never enters command arguments or logs. A compact success or
failure message covers the whole run, rather than sending five separate
messages. Discord delivery errors are reported separately from the persisted
backup result; notification delivery does not undo completed backups.

The initial service runs independently of the controller/chat. It is transient
and does not resume automatically after a host reboot. After successful
activation, the nightly cron job persists in the TrueNAS configuration.
The runner stores `last-run.json` and, for the initial run, `initial-run.json`
in its protected working directory.

Read-only status checks:

```sh
systemctl status truenas-e2-initial-backup.service
journalctl -u truenas-e2-initial-backup.service --no-pager -n 20
```

Inspect native job progress under **Data Protection → Cloud Backup Tasks**.
Inspect the nightly runner under **System → Advanced Settings → Cron Jobs**.
The initial live check confirmed successful system/app-settings backups and
an active application-data backup. The nightly cron entry was still absent,
as required before all five scopes complete.

## One-time clips restore verification

The user requested a real restore test after the initial clips upload.
`verify_clips.py --job-id 80875` waits for that exact native job to succeed.
It restores three nonempty clips, each at most 256 MiB, into a new protected
directory under `_cloud-backup/restore-test/`. It compares SHA-256 hashes with
the originals before and after restore, and checks restored file sizes.
Original files are never overwritten. The test retains its restored files.

The one-time `truenas-e2-clips-restore-test.service` runs independently of the
backup runner, so Archive can continue uploading during the restore. It sends
a Discord result and saves the snapshot ID, file sizes, and hashes in
`/mnt/gaia/appdata/_cloud-backup/clips-restore-test.json`. A failed upload stops
the test without restoring. This service does not resume after a host reboot.
The nightly backup schedule does not repeat this one-time test.
