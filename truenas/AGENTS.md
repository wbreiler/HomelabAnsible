# Agent Guidance

## Purpose

This repository manages the complete desired configuration of the TrueNAS host
`erebus` with Ansible. Prefer supported TrueNAS middleware APIs over direct
edits to the appliance filesystem or database.

## Safety Rules

- Read `README.md` before changing playbooks or operating the live host.
- Discovery must be read-only. Store sanitized discovery output under
  `artifacts/`; never commit secrets, tokens, password hashes, private keys, or
  raw configuration databases.
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
  high-risk changes.
- Apply one configuration domain at a time, validate live health, and run it a
  second time to prove `changed=0`.

## Repository Conventions

- Inventory belongs in `inventory/`.
- Desired state belongs in `group_vars/` or `host_vars/`, separated by domain.
- Reusable API logic belongs in `roles/`.
- Read-only inventory tooling belongs in `playbooks/discover.yml`.
- The main convergence entry point is `site.yml`.
- Use fully qualified Ansible collection names.
- Give every task a descriptive name and tag it by configuration domain.
- Prefer assertions that fail safely over permissive defaults.

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
