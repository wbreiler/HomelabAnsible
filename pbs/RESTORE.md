# Restore PBS backups from IDrive e2

Use this guide for guest recovery or file extraction from the encrypted cloud
copy. Read [CLOUD-BACKUP.md](CLOUD-BACKUP.md) for the deployment details.

## Recovery materials

| Item | Location or value |
| --- | --- |
| PBS host | `mnemosyne`, `10.10.20.2:8007` |
| Cloud datastore and bucket | `pbs-backup` |
| Namespace | Usually `cluster-nash`; select the namespace that contains the guest |
| S3 endpoint | `s3.us-east-1.idrivee2.com`, region `us-east-1`, HTTPS, path-style |
| Encryption key on PBS | `/root/pbs-e2-setup-2026-10-22/idrive-e2-recovery.key` |
| Encrypted controller key | `pbs/artifacts/idrive-e2-recovery-2026-10-22.key.vault` |
| Vault password file on controller | `~/.config/ansible/vault-passwords/kuma` |

The artifact is **gitignored**. A Git clone alone cannot recover these backups.
Preserve the encrypted key and vault password outside PBS and this checkout.
Also preserve IDrive account access. If the S3 secret is lost, create a new key
for the existing bucket through IDrive; it does not replace the encryption key.
PBS login credentials and the S3 access key do not decrypt backup data.

Use a completed snapshot. An unfinished initial sync does not establish a
complete offsite copy. Prefer the local `mneme` copy when it is available and
healthy; use `pbs-backup` to test or recover from the cloud copy.

## Recover the encryption key

On the controller, from `pbs/`, create a private temporary directory:

```sh
umask 077
PBS_RECOVERY_DIR=$(mktemp -d)
ansible-vault decrypt \
  --vault-password-file ~/.config/ansible/vault-passwords/kuma \
  --output "$PBS_RECOVERY_DIR/idrive-e2.key" \
  artifacts/idrive-e2-recovery-2026-10-22.key.vault
chmod 600 "$PBS_RECOVERY_DIR/idrive-e2.key"
```

Transfer the key through an authenticated encrypted channel to the recovery
client, or upload it through the Proxmox VE storage encryption interface.
Do not paste its contents into chat, logs, command arguments, or Git.
After recovery, remove only the temporary plaintext copy. Keep the encrypted
artifact and its independent password backup.

## Restore a VM or container through Proxmox VE

**Restoring over an existing guest can destroy its current disks.** Use a new,
unused VMID and keep the recovered guest disconnected from production networks
until validation. Check the live cluster and inventory before choosing a VMID.

1. Add or select a Proxmox Backup Server storage in Proxmox VE. Use server
   `10.10.20.2`, datastore `pbs-backup`, and the guest's namespace.
2. Verify the PBS certificate fingerprint through a trusted connection. Use a
   PBS identity with restore/read permission, then load `idrive-e2.key` in the
   storage's encryption settings. The local source key may differ from this
   cloud encryption key.
3. Select the completed guest snapshot in the storage's backup list. Restore
   to the unused VMID and reviewed target storage, with automatic startup off.
4. Check recovered disks and configuration before an isolated boot. Confirm
   application data, services, and the expected recovery date.
5. Reconnect production networking only after validation and a cutover decision.

## Extract files with the PBS client

Run these commands on a Linux recovery host with `proxmox-backup-client`.
Authenticate interactively; do not put passwords or token secrets in arguments.
Verify the certificate fingerprint before accepting an unfamiliar server.

```sh
export PBS_REPOSITORY='root@pam@10.10.20.2:pbs-backup'
proxmox-backup-client snapshot list --ns cluster-nash
```

Choose the actual snapshot timestamp from the output. For example:

```sh
PBS_SNAPSHOT='ct/102/REPLACE_WITH_TIMESTAMP_FROM_LIST'
proxmox-backup-client snapshot files "$PBS_SNAPSHOT" --ns cluster-nash
```

Use the archive name shown by that command. A container's `root.pxar.didx`
archive is addressed as `root.pxar` when restoring:

```sh
umask 077
PBS_RESTORE_DIR=$(mktemp -d /var/tmp/pbs-restore.XXXXXX)
proxmox-backup-client restore "$PBS_SNAPSHOT" root.pxar "$PBS_RESTORE_DIR" \
  --repository "$PBS_REPOSITORY" --ns cluster-nash \
  --keyfile /SECURE/RECOVERY/PATH/idrive-e2.key
```

Replace the key path before execution. Use a new destination and retain the
default refusal to overwrite files. VM `.img` archives are disk images, not
pxar directories; use Proxmox VE guest/file restore for those.

Compare restored files against stable originals when available:

```sh
sha256sum /PATH/TO/ORIGINAL "$PBS_RESTORE_DIR/PATH/TO/RESTORED_FILE"
```

Both hashes must match. If originals are unavailable, verify the backup date,
expected files, database integrity, and an isolated application or guest boot.
A successful command alone does not establish application recovery.

## If the PBS host is lost

This is a recovery procedure for a replacement host, not a command to run on
the current PBS server. Use PBS 4.2.8 or a compatible newer release with S3
support. The bucket contains a PBS datastore, not standalone restic archives.

1. Confirm the old PBS instance cannot access the cloud datastore. Two PBS
   instances must not operate on the same S3 datastore concurrently.
2. On the replacement PBS host, configure the S3 endpoint through the PBS UI:
   ID `idrive-e2-virginia`, endpoint and region from the table, HTTPS and
   path-style enabled. Enter the current bucket credentials in secret fields.
3. Prepare a persistent local cache directory on reviewed storage, with
   sufficient free space. The original cache had a 64 GiB quota. Do not point
   this at an existing ordinary datastore or create/reformat a pool blindly.
4. Reattach the existing cloud datastore with the **same name** `pbs-backup`.
   Once the old instance is definitively offline, run:

   ```sh
   proxmox-backup-manager datastore create pbs-backup /RECOVERY/CACHE/PATH \
     --backend 'type=s3,client=idrive-e2-virginia,bucket=pbs-backup' \
     --reuse-datastore true --overwrite-in-use true
   ```

5. List completed snapshots and restore with the recovery key as described
   above. Keep sync, pruning, and garbage collection unscheduled during recovery.

**The takeover flags override the old datastore ownership marker.** Never use
these flags while the original instance remains active. Do not initialize a
new bucket, change the datastore name, or manually rearrange S3 objects.
The cache can be rebuilt; the cloud objects and encryption key are essential.

See the official [S3 datastore recovery documentation](https://pbs.proxmox.com/docs/storage.html#s3-object-storage)
and [backup client guide](https://pbs.proxmox.com/docs/backup-client.html).

## Validation record and limits

The encrypted fixture upload and restore passed SHA-256 checks on 2026-10-22.
Installed PBS 4.2.8 command help was checked for this guide on 2026-10-23.
A complete production guest restore and replacement-host takeover have not
been rehearsed. No recovery mutation was performed while writing this guide.
