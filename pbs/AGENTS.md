# AGENTS.md

Guidance for the PBS host project. Follow the [root guidance](../AGENTS.md)
and [README](README.md). Run Ansible from `pbs/` so its inventory, SSH settings,
and role paths apply.

## Scope and ownership

`site.yml` targets `pbs_servers`. It configures an existing PBS installation
and an existing local ZFS pool. It does not install PBS or create a pool.
Terraform owns PVE guest backup jobs, HA policy, and the PVE-to-PBS connection.
Do not add those owners to this project.

Native IDrive e2 storage and encrypted push sync are documented in
[CLOUD-BACKUP.md](CLOUD-BACKUP.md). The local datastore role does not reconcile
that configuration. Read [RESTORE.md](RESTORE.md) before recovery work.
Its encryption keys and credentials are independent recovery requirements.

## Entry points and implementation limits

| Role | Behavior and boundary |
| --- | --- |
| `cleanup_repos` | Removes the listed legacy repository files and refreshes APT metadata |
| `tailscale` | Installs the client and optionally authenticates through a temporary secret file |
| `pbs` | Validates the existing pool/mountpoint, optionally creates a dataset, and registers datastore/namespaces and pull-style sync |
| `users` | Creates missing PBS users, grants `DatastoreAdmin` at `/datastore`, and optionally changes the Unix root password |

The Tailscale gate defaults to enabled. Its repository still targets Bookworm.
Review that implementation before a Debian 13 run. A full `site.yml` run is
not read-only and has no global mutation gate.

The `pbs` role accepts existing remotes and sync jobs without reconciling
their settings. The users role does not rotate passwords for existing PBS
users. Do not claim full reconciliation or repeat-run `changed=0` from syntax
checks or an accepted `already exists` response.

## Local configuration and safety

- Copy `inventory.yml.example` and `group_vars/pbs_servers.yml.example` into
  their ignored local paths. Keep passwords encrypted and `.vault_pass` private.
  Use the configured SSH agent for routine access. Password SSH is bootstrap-only.
- The examples use `MainStore`, `backup/pbs`, and `/mnt/datastore`. These are
  not the recorded `mneme` deployment. Verify the actual pool, dataset,
  mountpoint, datastore, and namespace before selecting values.
- Preserve mountpoint assertions and `pbs_zfs_create_dataset`. Never change
  pool topology, delete backup data, or replace an existing datastore to make
  an example pass. Destructive recovery requires explicit target approval.
- Preserve secret prompts, `PBS_PASSWORD`, temporary-file cleanup, and
  `no_log: true`. Do not put passwords, tokens, or encryption keys in argv,
  logs, documentation, or Git. Review the users role's broad ACL before use.
- Preserve cloud encryption and `remove-vanished: false` unless a separate
  reviewed change authorizes different retention. Test restores in a new
  destination or isolated guest. Never run two PBS writers against one cloud datastore.

Host versions, kernel state, backup counts, and VM 108 retirement in the
guides are dated evidence. Recheck them before operational decisions.

## Validation

Run static checks from this directory:

```sh
ansible-lint
ansible-playbook site.yml --syntax-check
git diff --check
```

Use the configured Vault access when needed. If local inventory is absent,
report the prerequisite. An example inventory can validate syntax but cannot
establish live configuration or connectivity.

For an authorized host change, review the selected role and use
`ansible-playbook site.yml --check --diff` with appropriate tags and Vault access.
Command-based PBS/ZFS tasks can limit check-mode results. Verify datastore
health and the affected service afterward. Verify actual restored contents
before claiming recovery, not merely backup presence or a successful command.
