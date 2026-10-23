# Restore TrueNAS backups from IDrive e2

Use a new recovery directory first. Restoring directly over production files
can destroy newer data. Read [SETUP.md](SETUP.md) for backup consistency and
exclusion details.

## Recovery materials and scope

| Item | Location or value |
| --- | --- |
| TrueNAS host | `erebus`, `10.10.10.7`, SSH port `2747` |
| Bucket | `truenas-backup` |
| Endpoint | `https://s3.us-east-1.idrivee2.com`, region `us-east-1` |
| Encrypted controller secrets | `truenas/artifacts/cloud-backup-secrets-2026-10-22.vault` |
| Vault password file on controller | `~/.config/ansible/vault-passwords/kuma` |

The vault contains `truenas_cloud_backup_access_key`,
`truenas_cloud_backup_secret_key`, and `truenas_cloud_backup_password`.
The last value is the **restic repository password**. It is independent of
both the S3 secret and the PBS recovery key.

The vault is gitignored. Preserve it and the vault password outside TrueNAS
and this checkout. A Git clone alone is insufficient for recovery.

| Repository prefix | Contents |
| --- | --- |
| `archive` | Archive collections, excluding YouTube |
| `clips` | Personal clips |
| `appdata` | Application files and consistent SQLite copies under `_cloud-backup/sqlite/` |
| `app-settings` | Exported application settings under `configs/` |
| `system-config` | Exported TrueNAS configuration, including secret seed and pool keys |

Each prefix is a separate encrypted restic repository with 30 retained
versions. Time Machine, replaceable media, downloads, and excluded caches are
not covered. The configuration export is not a backup of all pool contents.

## Restore through the existing TrueNAS host

Use the supported middleware API over SSH. Do not enable the disabled native
task schedules; the separate nightly runner owns scheduling.

1. Connect through the existing trusted SSH configuration. Locate the desired
   task without displaying its password or cloud credentials:

   ```sh
   ssh -p 2747 root@10.10.10.7
   ```

   ```sh
   python3 - <<'PY'
   from truenas_api_client import Client
   with Client() as client:
       for task in client.call('cloud_backup.query'):
           print(task['id'], task['description'])
   PY
   ```

2. List snapshots for the selected task. The examples below use clips task
   `2`; confirm that ID first. Copy the full snapshot ID you want to recover.

   ```sh
   midclt call cloud_backup.list_snapshots 2
   ```

3. Browse the snapshot from `/`, not the original `/mnt/gaia/...` path:

   ```sh
   midclt call cloud_backup.list_snapshot_directory 2 'SNAPSHOT_ID' '/'
   ```

   These relative-path backups store their contents at the repository tree's
   root, although snapshot metadata records the original source directory.
   Descend into the returned paths to locate a file or folder.

4. Restore a selected file into a new protected directory. Run this on
   TrueNAS, replacing the snapshot ID and include path from the listing:

   ```sh
   python3 - <<'PY'
   import os
   from pathlib import Path
   import tempfile
   from truenas_api_client import Client
   os.umask(0o077)
   parent = Path('/mnt/gaia/appdata/_cloud-backup/restore-test')
   parent.mkdir(mode=0o700, exist_ok=True)
   destination = tempfile.mkdtemp(prefix='manual-', dir=parent)
   with Client() as client:
       client.call('cloud_backup.restore', 2, 'SNAPSHOT_ID', '/', destination,
                   {'include': ['/PATH/IN/SNAPSHOT.mp4']}, job=True, timeout=None)
   print('Restored into:', destination)
   PY
   ```

   Include paths are restic patterns. Use paths from the snapshot listing;
   escape pattern metacharacters when a literal filename contains them.
   To restore the entire selected scope, replace the options with `{}` after
   confirming sufficient destination capacity.

5. Compare SHA-256 hashes with stable originals, then inspect the restored
   content. Matching hashes establish byte equality:

   ```sh
   sha256sum /mnt/gaia/clips/PATH/IN/SNAPSHOT.mp4 \
     /mnt/gaia/appdata/_cloud-backup/restore-test/manual-REPLACE/PATH/IN/SNAPSHOT.mp4
   ```

The `restore-test` directory is excluded from appdata uploads. Restored files
remain available for inspection. Delete only the selected test directory after
review; never run cleanup against the source datasets.

## Recover without the original TrueNAS host

Use a Linux recovery host with restic compatible with the original 0.16.4
repository. No TrueNAS database or original backup task is required for file
recovery. Use the controller to decrypt the vault into a private temporary
file, from `truenas/`:

```sh
umask 077
TRUENAS_RECOVERY_DIR=$(mktemp -d)
ansible-vault decrypt \
  --vault-password-file ~/.config/ansible/vault-passwords/kuma \
  --output "$TRUENAS_RECOVERY_DIR/secrets.yml" \
  artifacts/cloud-backup-secrets-2026-10-22.vault
chmod 600 "$TRUENAS_RECOVERY_DIR/secrets.yml"
```

Read the needed values privately from that protected file. Transfer them over
an authenticated encrypted channel if the Linux recovery host is separate.
Do not paste secrets into command arguments, shell history, logs, or Git.
The following commands use **Bash** prompts without echo. Do not enable shell
tracing (`set -x`):

```bash
read -r -s -p 'IDrive access key: ' AWS_ACCESS_KEY_ID; printf '\n'
read -r -s -p 'IDrive secret key: ' AWS_SECRET_ACCESS_KEY; printf '\n'
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION=us-east-1
export RESTIC_REPOSITORY='s3:https://s3.us-east-1.idrivee2.com/truenas-backup/clips'
restic snapshots
```

Restic prompts for `truenas_cloud_backup_password`. Replace only the final
`clips` prefix to select another scope. Do **not** run `restic init`, `forget`,
`prune`, or any upload command against a recovery repository.

List a chosen snapshot and restore selected files into a new directory:

```sh
restic ls SNAPSHOT_ID
umask 077
RESTIC_RESTORE_DIR=$(mktemp -d /var/tmp/truenas-restore.XXXXXX)
restic restore SNAPSHOT_ID --target "$RESTIC_RESTORE_DIR" \
  --include '/PATH/IN/SNAPSHOT.mp4'
```

Omit `--include` only when intentionally restoring the entire scope. Compare
hashes or perform application integrity checks before promoting restored data.
Clear credential variables and remove only temporary plaintext secret copies
when finished. Keep the encrypted vault and its independent password backup.

## Application and system recovery

1. Restore `app-settings` and `appdata` into staging. Restore the matching
   `system-config` export when rebuilding the appliance configuration.
2. Prefer consistent SQLite copies from `_cloud-backup/sqlite/` over raw live
   database files. Check SQLite integrity; Plex needs its own SQLite tool for
   the ICU collation. Other applications may require their own recovery tools.
3. Before replacing production application data, stop the affected application
   through supported TrueNAS controls. Preserve current data and review file
   ownership, permissions, and any stale WAL/SHM sidecars with the database.
4. Reinstall or recreate applications through supported TrueNAS controls using
   the restored settings. Exported app settings are reference material, not a
   tested universal application-import bundle. Validate each application before
   reconnecting it to production clients.
5. To restore appliance configuration, use TrueNAS's supported configuration
   upload on a compatible release. Configuration import can change networking
   and restart the host. Review pool encryption material and arrange console
   access before import. Do not restore by overwriting the live config database.

Pool creation/import, dataset changes, application shutdowns, and configuration
import require a separate reviewed recovery action. They are not performed by
file extraction. This cloud backup does not preserve excluded data.

## Verified results and limits

On 2026-10-23, three production clips totaling 180,822,910 bytes were restored
from IDrive e2. All restored SHA-256 hashes matched the originals. The report
is `/mnt/gaia/appdata/_cloud-backup/clips-restore-test.json`; the tested snapshot
is `b8aa46ced94bba628489e3789dec78ddb5833d4a621fb5d5094c5432022124f3`.
A separate synthetic restore also passed, including its SQLite record check.

Whole-host recovery, full Archive restore, and production application recovery
have not been rehearsed. The three-clip test does not verify every cloud file.
