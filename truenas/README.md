# AnsibleTrueNAS

Ansible-managed desired state for the TrueNAS host `erebus`.

## Target

| Setting | Value |
| --- | --- |
| Address | `10.10.10.7` |
| SSH port | `2747` |
| SSH user | `root` |
| Reported release | TrueNAS Community Edition `25.10.4` |
| Authentication | SSH key via the local 1Password SSH agent |

The exact platform and release are verified by read-only discovery rather than
assumed from the reported product name.

## Project Status

Read-only discovery and the desired-state model were completed on 2026-07-18.
A protected configuration backup was captured before the approved cleanup.
The complete convergence playbook subsequently passed twice with
`ok=283`, `changed=0`, and no failures.

The repository currently:

- audits singleton system settings and service enablement for drift;
- models the pool's root and all 25 child datasets;
- manages the remaining SMB share and seven NFS exports, plus explicit
  `state: absent` guards for the removed legacy shares;
- models both configured network interfaces;
- reconciles NTP servers, cron jobs, init scripts, snapshot tasks, and pool
  scrub schedules;
- models the local non-built-in accounts without their non-retrievable
  passwords;
- models Docker settings and manages the `llama-cpp`, `sabnzbd`, and `plex`
  applications;
- idempotently reconciles singleton settings, service enablement, storage,
  sharing, identity, applications, network interfaces, and schedules;
- never deletes objects merely because they are absent from desired state.

The explicitly approved disabled legacy shares and periodic snapshot task
under `/mnt/pool` are recorded with `state: absent` and continuously audited so
that accidental recreation is detected.

The former `bldrbackup` home was replaced with the managed
`gaia/backups/storage-bldr-1` dataset. Existing SSH/password settings were
preserved, and ownership/mode converge to UID `3003`, GID `3004`, and `0700`.

Mutation remains deliberately disabled by default. Each run must opt in with
`truenas_allow_changes=true`; destructive changes and management-access
changes have separate gates.

The local backup is stored as the ignored mode-`0600` artifact
`artifacts/erebus-config-2026-07-18.tar`. It includes the configuration
database, secret seed, and administrator/root authorized keys and must be
handled as a credential-bearing file.

## Design

TrueNAS is an appliance. This project therefore uses Ansible as the
orchestrator while managing supported TrueNAS middleware APIs, rather than
editing generated configuration files or the internal configuration database.

The workflow is:

1. Discover the current configuration without changing the host.
2. Sanitize and review the inventory.
3. Encode each configuration domain as explicit desired state.
4. Back up the TrueNAS configuration.
5. Apply and validate one domain at a time.
6. Re-run each domain and require idempotent `changed=0` results.

High-risk operations—storage deletion, ACL replacement, network changes,
account removal, encryption changes, and changes that could remove management
access—remain explicitly gated.

## Authentication

The public key is available locally as `~/.ssh/erebus.pub`; the corresponding
private key is provided by the 1Password SSH agent. Do not copy the private key
or any API credential into this repository.

Ansible will use the agent:

```sh
ssh -p 2747 root@10.10.10.7
```

1Password may ask for biometric approval when the key is first used.

## Local Configuration

The tracked repository contains examples only. Create the ignored local
configuration before running Ansible:

```sh
cp inventory/hosts.yml.example inventory/hosts.yml
cp group_vars/truenas.yml.example group_vars/truenas.yml
mkdir -p inventory/host_vars/nas1
cp inventory/host_vars/nas1/desired_state.yml.example \
  inventory/host_vars/nas1/desired_state.yml
cp inventory/host_vars/nas1/vault.yml.example \
  inventory/host_vars/nas1/vault.yml
```

Rename the example inventory host and matching `host_vars` directory as needed.
Populate `desired_state.yml` from reviewed discovery output and encrypt
`vault.yml` before adding credentials. These generated `.yml` files are ignored
so appliance addresses, datasets, shares, accounts, and application settings
remain local.

## Layout

```text
.
├── AGENTS.md
├── README.md
├── ansible.cfg
├── inventory/                      # Ignored local inventory + tracked examples
├── group_vars/                     # Ignored local variables + tracked examples
├── inventory/host_vars/            # Ignored desired state/Vault + examples
├── playbooks/
├── roles/
├── artifacts/
└── site.yml
```

## Commands

Use the 1Password SSH agent for authentication. If a headless Ansible process
cannot trigger the biometric prompt, open a temporary control connection in a
separate Terminal:

```sh
ssh -M -S /tmp/ansible-truenas-erebus.sock \
  -o ControlPersist=30m \
  -fN -p 2747 root@10.10.10.7
```

Run read-only discovery:

```sh
ANSIBLE_SSH_ARGS="-o ControlMaster=no \
-o ControlPath=/tmp/ansible-truenas-erebus.sock" \
ansible-playbook playbooks/discover.yml
```

Run the read-only desired-state audit:

```sh
ANSIBLE_SSH_ARGS="-o ControlMaster=no \
-o ControlPath=/tmp/ansible-truenas-erebus.sock" \
ansible-playbook playbooks/audit.yml
```

Mutation through `site.yml` is blocked by default. It requires
`truenas_allow_changes=true` and a reviewed backup:

```sh
ANSIBLE_SSH_ARGS="-o ControlMaster=no \
-o ControlPath=/tmp/ansible-truenas-erebus.sock" \
ansible-playbook site.yml -e truenas_allow_changes=true
```

Add `-e truenas_allow_destructive_changes=true` only for reviewed explicit
`state: absent` entries. Network and other management-access changes separately
require `-e truenas_allow_management_access_changes=true`.

Appliance-generated certificates, built-in privileges, Docker-generated
networks, and credential-backed keychain/cloud/alert objects are discovered but
not recreated as ordinary cleartext entities. Credential-backed reconciliation
is completed only after populating and encrypting `vault.yml`.

## Safety

Read [AGENTS.md](AGENTS.md) before operating on the live host. In particular:

- Discovery is read-only.
- Absence from desired state never implies deletion.
- Secrets and raw TrueNAS databases are never committed.
- A configuration backup precedes mutation.
- Destructive and management-access changes require explicit approval.

See [REVIEW.md](REVIEW.md) for notable reliability and security observations
from discovery. They are documented rather than silently changed.
