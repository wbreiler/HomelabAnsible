# PBS cloud backup

## Verified configuration — 2026-10-22

PBS 4.2.8 has an IDrive e2 S3 datastore named `pbs-backup`. Its endpoint is
`s3.us-east-1.idrivee2.com`, in Virginia (`us-east-1`), with HTTPS and path-style
addressing. The endpoint configuration ID is `idrive-e2-virginia`.

The user approved the full sync and a nightly PBS schedule after the initial
sync succeeds. The initial encrypted sync started on 2026-10-22 at 21:00
America/Chicago. Live checks confirmed the first production archive uploads.
The complete offsite copy is not yet established.

| Setting | Configured value |
| --- | --- |
| Local source datastore | `mneme` |
| Cloud datastore and bucket | `pbs-backup` |
| Persistent cache dataset | `mneme/idrive-e2-cache` |
| Cache mountpoint | `/mnt/datastore/idrive-e2-cache` |
| Cache quota | 64 GiB |
| Full sync job | `idrive-e2-offsite` |
| Parallel groups | 2 (`worker-threads`) |
| Direction | Push through `e2-local-writer` on localhost |
| Namespace depth | 7, including source namespaces |
| Encryption key ID | `idrive-e2` |
| Remove vanished backups | Disabled |
| Nightly schedule | 03:00 America/Chicago, enabled only after initial success |
| Automatic pruning | Not configured |
| Completion notifications | Discord, on sync success or failure |

The loopback writer `e2-sync@pbs!cloud` and its parent account have
`DatastoreAdmin` only on `/datastore/pbs-backup`. Push sync encrypts plaintext
source snapshots before upload and preserves already encrypted snapshots.
The existing local datastore and remote sync job remain intact.

Credentials stay in protected PBS configuration. Never copy credentials into
tracked files, command arguments, or logs. This setup uses native PBS
configuration; the existing local-datastore Ansible role does not manage it.
Do not run the local role with example defaults to modify this configuration.

## Tests passed

A four-file fixture contains 35,782,702 bytes, including 32 MiB of random
content, compressible text, an empty file, and a nested file.

- Direct encrypted upload used `--no-cache true`. The restore matched all
  original SHA-256 hashes.
- A separate plaintext fixture backup in `e2-smoke-source` was pushed through
  encryption to the cloud `validation` namespace. Its decrypted restore
  matched all original hashes.
- Cloud snapshot metadata reports `crypt-mode=encrypt` for the fixture archive.
- S3 counters confirmed 67,111,912 downloaded bytes, demonstrating remote
  object reads rather than only local-cache reads.
- All temporary administrator tokens were revoked. The synthetic permission
  probe object was deleted. No full sync was started during these tests.

Synthetic snapshots, the small test datastore, and its unscheduled
`idrive-e2-smoke` job remain available for inspection. They contain no user
backup data. Test inputs, restored files, and the result JSON remain in the
protected `/root/pbs-e2-setup-2026-10-22` directory on PBS.

A client restore can finish successfully while its server reader task reports
`connection error: not connected` when the client closes the connection.
The completed client exit status and independent file hashes establish these
restore results. Investigate any future reader error together with the client
result rather than assuming the restore succeeded.

## Recovery key

The automation key is protected by root-only filesystem permissions on PBS.
A second copy on the controller is encrypted with **Ansible Vault using the
existing Kuma vault password**. It is stored in the ignored directory as
`pbs/artifacts/idrive-e2-recovery-2026-10-22.key.vault`. Its decryption was
verified in memory without writing plaintext on the controller.

Keep the vault password and encrypted recovery copy available outside PBS.
Losing the encryption key prevents restoring the encrypted cloud backups.
The original IDrive credential export has the old, insufficient key; use the
current IDrive credential or protected PBS configuration for recovery.

## Initial sync and nightly schedule

The host-managed `pbs-e2-initial-sync.service` runs the initial
`idrive-e2-offsite` job independently of the controller and chat. Its shell
uses `set -eu` and executes the schedule update only after the sync command
exits successfully:

```sh
proxmox-backup-manager sync-job run idrive-e2-offsite
proxmox-backup-manager sync-job update idrive-e2-offsite --schedule '03:00'
```

Once enabled, PBS itself runs the persistent nightly job at 03:00 in the
host's verified `America/Chicago` timezone. The service does not install a
cron job or a separate recurring timer. If the initial sync fails, the
schedule remains absent. Inspect its task log before retrying. The initial
service is transient and does not restart automatically after a host reboot.

No pruning or retention policy was added. Until retention is configured,
cloud backup history accumulates. The initial local source measurement was
approximately 761 GB. Cloud usage can differ because encryption during sync
affects chunk deduplication.

## Discord completion notifications

PBS uses a native webhook target named `discord`, securely reused from the
existing Proxmox Discord destination. The webhook credential is stored in
PBS's root-only `notifications-priv.cfg`, not in this repository or command
arguments. The target reuses the existing compact Discord embed template,
which contains the notification title, severity, job ID, time, and hostname.
It does not insert a potentially oversized sync log into the Discord message.

The native matcher `idrive-e2-discord` requires both
`exact:type=sync` and `exact:job-id=idrive-e2-offsite`. It has no severity
restriction, so both successful and failed completion events route to
Discord. This covers the running initial sync and future nightly runs.
The existing email matcher remains intact.

The Discord target test delivered successfully on 2026-10-22. The matcher
configuration was read back and verified. The temporary configuration token
was restricted to `/system/notifications` and revoked afterward. Actual
initial-sync completion delivery remains pending while the job runs.

Useful read-only checks:

```sh
systemctl status pbs-e2-initial-sync.service
journalctl -u pbs-e2-initial-sync.service --no-pager -n 30
proxmox-backup-manager sync-job show idrive-e2-offsite --output-format json
proxmox-backup-manager notification matcher show idrive-e2-discord --output-format json
proxmox-backup-manager task list --all true --output-format json
proxmox-backup-debug api get /admin/datastore/pbs-backup/status --output-format json
zfs get quota,mountpoint mneme/idrive-e2-cache
```

## Parallel sync tuning — 2026-10-23

The user approved restarting the initial cloud sync with two parallel groups.
The original task was stopped through the native PBS task API, then the job
was updated with `--worker-threads 2` and the initial service was recreated.
The service retains its success-gated 03:00 nightly schedule update and
Discord completion matcher. Encryption, namespace depth, and retention were
unchanged. This is native PBS configuration, outside the existing Ansible role.

The resumed task skipped completed snapshots and opened two concurrent
cloud writer tasks. It also included new source snapshots created since
the original run started; progress percentages therefore restart. An
unfinished archive can require reprocessing after restart.

A one-minute pre-change sample found no S3 uploads while approximately one
CPU core was active. This is a processing interval, not a sustained bandwidth
benchmark. Compare multi-minute S3 counter deltas and CPU/I/O pressure after
the restart; logical archive throughput in task logs is not network throughput.

The first two-minute follow-up averaged approximately 1.15 MB/s of actual S3
uploads, with individual 20-second windows ranging from 0.22 to 2.58 MB/s.
CPU idle time was approximately 49–50%, compared with 74–75% before restart.
Concurrent archive processing reached approximately 100 and 78 MiB/s, but
these are logical processing rates and must not be added as network rates.
Disk wait increased, without persistent queues in the sampled intervals.
The sync remained active with no errors in the inspected new task log.

These samples covered small incremental updates in previously completed
groups. They demonstrate functioning concurrency and greater CPU use, but
do not establish a sustained upload speedup or a revised completion time.
Two workers remain configured; no additional tuning was applied.
