# PBS cloud backup

## IDrive e2 preparation — 2026-10-22

The user approved configuration and a small backup/restore test. A full sync
requires separate approval after the test passes. Do not attach a schedule or
start the full sync before that approval.

The live PBS endpoint `idrive-e2-virginia` uses HTTPS, path-style addressing,
and region `us-east-1`. Use the endpoint inside the credential export, not its
filename. Credentials remain in the protected PBS configuration. Never copy
them into this document, command arguments, or logs.

Preparation stopped at the access check. The key could list the bucket and
upload a synthetic object, but object reads and deletion returned HTTP 403.
The temporary administrator token was revoked. No cloud datastore, writer
account, encryption key, cloud sync job, or bulk backup was created.

## Required permissions

Restrict the IDrive key to the intended backup bucket. Select **Read and
write** and permit **object deletion**. Bucket deletion can remain disabled.
PBS requires object reads for restore and object deletion for cleanup.

After the key is corrected, repeat:

```sh
proxmox-backup-manager s3 check idrive-e2-virginia pbs-backup
```

One small synthetic `pbs-permission-test-*` object remains because the denied
deletion prevented test cleanup. It contains no user data. Remove only that
test object after permissions are corrected.

## Approved test design

1. Create a separate S3 datastore with a persistent 64 GiB cache quota.
2. Create an encryption key and preserve a protected recovery copy off PBS.
3. Upload a small encrypted fixture with chunk caching disabled, then restore
   it and compare every file using SHA-256.
4. Test the production path separately: local plaintext fixture, encrypted
   push sync through a restricted loopback writer, then decrypted restore.
5. Revoke the temporary administrator token and report the results. Leave
   the full sync unscheduled until separately approved.

Keep the existing local datastore and its sync job intact. The cloud job must
include all source namespaces, use `remove-vanished=false`, and preserve
existing client encryption. Do not introduce cloud retention or pruning
without reviewed settings. This setup uses native PBS configuration; the
existing local-datastore Ansible role does not manage it.
