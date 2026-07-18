# Discovery Review

Read-only discovery was performed against `erebus` on 2026-07-18. Subsequent
approved changes are recorded below.

## High Priority

### Pool redundancy

The `gaia` pool is healthy and online, but its data topology consists of three
top-level disks rather than a mirror or RAIDZ vdev. This is effectively striped
storage: loss of any one data disk can lose the pool.

The pool also has one non-redundant log device. Its failure behavior and the
workloads that require synchronous writes should be reviewed before any
storage-topology change.

No playbook attempts to recreate, expand, detach, or otherwise mutate this pool.
Those operations require a separate backup/migration plan and explicit
approval.

## Security Hardening Decisions

The current configuration is faithfully represented, but the following choices
should be reviewed rather than normalized automatically:

- SSH password authentication is enabled.
- The SSH password-login groups include `root`.
- SSH permits `AES128-CBC` and `NONE` in the weak-cipher setting.
- FTP is enabled and running without TLS.
- The web UI listens on HTTP port `85`; HTTPS redirect is disabled.
- SMB and NFS are enabled and running.
- NFS exports with empty host/network restrictions are reachable according to
  the surrounding network and firewall policy.

Changing any of these can break clients or management access. Harden them one
at a time after confirming dependencies.

## Legacy References

Several disabled shares and one account home path referred to `/mnt/pool`,
although the only discovered imported pool is `gaia`.

After explicit approval and a verified configuration backup:

- SMB shares `backups`, `isos`, and `lanwar` were removed.
- Disabled NFS export `/mnt/pool/data` was removed.
- Disabled periodic snapshot task for `pool/data` was removed.
- Their desired-state entries are retained as `state: absent` assertions.

The `bldrbackup` account was retained with its existing login methods. Its home
was migrated to the new `gaia/backups/storage-bldr-1` dataset and verified with
UID `3003`, primary GID `3004`, and mode `0700`.

## Secrets and Generated Material

TrueNAS does not return reusable account passwords. Application discovery
returned a Plex claim token, but the committed desired state replaces it with
`vault_plex_claim_token`. Raw discovery and appliance-generated SSH host keys
remain only in ignored, mode-`0600` local artifacts.

Copy `inventory/host_vars/erebus/vault.yml.example` to `vault.yml`, populate the
required values, and encrypt it with Ansible Vault before enabling secret
reconciliation.

Appliance-generated certificates, built-in privileges, Docker-generated
networks, and credential-backed keychain/cloud/alert records remain
discovery-only. They should not be copied blindly from raw discovery; portable
credential-backed definitions belong in the encrypted Vault workflow.
