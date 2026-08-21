# Agent Guidance

## Purpose

This repository manages the complete desired configuration of the TrueNAS host
`erebus` with Ansible. Prefer supported TrueNAS middleware APIs over direct
edits to the appliance filesystem or database.

## Safety Rules

- Read `README.md` before changing playbooks or operating the live host.
- Prefer `playbooks/audit.yml` for desired-state drift checks. It enables the
  roles' audit-only paths and does not reconcile detected drift.
- Discovery must be read-only. Store sanitized discovery output under
  `artifacts/`; `playbooks/discover.yml` writes the ignored, mode-`0600`
  `artifacts/erebus-raw.json`. Never commit secrets, tokens, password hashes,
  private keys, raw discovery, or raw configuration databases.
- Never modify the TrueNAS boot pool, data pools, datasets, network interfaces,
  default route, SSH service, or the account used by Ansible unless the user
  explicitly approves that exact change.
- Treat pool, dataset, snapshot, replication, encryption, ACL, network, and
  account deletions as destructive. Require explicit approval immediately
  before applying them.
- Do not infer that an object missing from desired state should be deleted.
  Deletion requires an explicit `state: absent` entry and user approval.
- Keep secrets in Ansible Vault or environment variables. Commit only examples
  and variable names.
- Back up the TrueNAS configuration before the first mutating run and before
  high-risk changes. `playbooks/backup.yml` exports secret material and root
  authorized keys to an ignored mode-`0600` artifact; treat that archive as a
  credential-bearing file and review its dated paths before reuse.
- Apply one configuration domain at a time, validate live health, and run it a
  second time to prove `changed=0`.

## Repository Conventions

- Local inventory belongs in ignored `inventory/hosts.yml`; keep only the
  sanitized `inventory/hosts.yml.example` tracked.
- Global gates belong in ignored `group_vars/truenas.yml`. Appliance desired
  state and Vault data belong in the matching ignored
  `inventory/host_vars/<host>/desired_state.yml` and `vault.yml`. Keep their
  sanitized `*.yml.example` templates tracked.
- Reusable API logic belongs in `roles/`.
- Read-only inventory tooling belongs in `playbooks/discover.yml`.
- Read-only desired-state auditing belongs in `playbooks/audit.yml`.
- The main convergence entry point is `site.yml`.
- `site.yml` requires `truenas_allow_changes=true`. Explicit deletions also
  require `truenas_allow_destructive_changes=true`; interface and other
  management-access changes require
  `truenas_allow_management_access_changes=true`.
- `playbooks/cleanup_legacy.yml` is a narrowly scoped, destructive migration
  playbook, not a general convergence entry point. Do not broaden or rerun its
  scope without verifying every target and obtaining explicit approval.
- Use fully qualified Ansible collection names.
- Give every task a descriptive name and tag it by configuration domain.
- Current convergence tags include `configuration`, `entities`, `system`,
  `security`, `shares`, `access`, `services`, `storage`, `network`,
  `schedules`, `identity`, and `apps`. Use the narrowest applicable tag set for
  reviewed runs.
- Prefer assertions that fail safely over permissive defaults.
- Network reconciliation stages interface changes with automatic rollback,
  confirms connectivity, and checks them in. Do not bypass that sequence.

## Validation

Run, at minimum:

```sh
ANSIBLE_LOCAL_TEMP=/tmp/ansible-truenas-local \
ANSIBLE_REMOTE_TEMP=/tmp/ansible-truenas-remote \
ansible-lint

ANSIBLE_LOCAL_TEMP=/tmp/ansible-truenas-local \
ANSIBLE_REMOTE_TEMP=/tmp/ansible-truenas-remote \
ansible-playbook --syntax-check site.yml

git diff --check
```

For any live change, first use `--check` where the underlying TrueNAS API
operation supports a meaningful check mode. Then apply only the selected tags,
verify services and storage health, and perform a second run expecting
`changed=0`.

Syntax checks use the ignored local inventory and variables. If they have not
been created from the tracked examples, report that prerequisite instead of
weakening inventory, authentication, or host-key checking.
