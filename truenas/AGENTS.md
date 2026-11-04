# Agent Guidance

## Purpose

This repository manages the complete desired configuration of the TrueNAS host
`erebus` with Ansible. Prefer supported TrueNAS middleware APIs over direct
edits to the appliance filesystem or database.

## Safety Rules

- Read `README.md` before changing playbooks or operating the live host.
- Prefer `playbooks/audit.yml` for desired-state drift checks. It enables the
  roles' audit-only paths and does not reconcile detected drift.
- TrueNAS 26 removes the legacy REST API. This project uses `midclt`, the
  supported JSON-RPC 2.0 WebSocket API client, over SSH. Do not replace it with
  `/api/v2.0` calls; audit any new external integration before upgrading.
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
- Send secret-bearing API payloads through stdin with `no_log: true`. Keep
  application configuration queries and mutation results out of logs and argv.
  Preserve the protected-input pattern in the entity and configuration roles.
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

## Application and backup workflows

- `playbooks/maintenance-queries.yml` installs the shared `maintenance_queries`
  role from `../proxmox/roles` and reconciles only its named cron job through
  middleware. Export a protected configuration backup first. Keep the worker
  and credentials under `/root/homelab-status` with root-only permissions.
  The minute cron worker polls every ten seconds within a bounded 50-second
  window under its existing exclusive lock. Long checks finish normally and
  overlap attempts exit without replay. Do not create another scheduler.
  Direct `--inspect` diagnostics must still return evidence while that polling
  lock is held. They must not change query state, cursors, or API counters.
  Preserve owner mentions and fixed read-only probes. Custom apps use live
  platform-aware registry/source comparisons; only OS availability is cached.
  Never pull image layers or rebuild/deploy apps during inspection. This
  workflow must not change SSH, accounts, pools, or network.
  Preserve the shared `query_nodes` order. Only its first host writes the main
  Discord summary; other hosts publish details inside the associated thread.
  See [query coverage](../proxmox/docs/maintenance-queries.md).
  The dedicated playbook also enables explicit app update proposals. Keep
  inspections read-only. Only an exact, unexpired owner-approved proposal may
  start the separate transient executor. A single-app request changes one
  platform-pinned image. An approved batch can change multiple listed images
  per app, retaining all other images/configuration and redeploying each app once.
  Keep fleet execution sequential, stop pending work after failure/cancellation,
  and publish exact version plans in the one channel summary's thread.
  Preparation may compare three images concurrently and reuse one fresh Docker
  inventory for that request. Execution must read current configuration and
  image identities again. Never share that snapshot across requests or writes.
  Keep apps absent from running-container inventory visible as unavailable in
  reports. Exclude stopped or unchecked apps explicitly instead of calling them
  current. Persist terminal delivery before closing local batch state.
  Reject RC, pre-release, and preview image versions before creating a proposal.
  Preserve delivery state during execution. A deleted reply must not block later
  report requests, recreate approval, or replay an update.
  Require recent successful backup evidence and preserve one-attempt semantics.
  Catalog apps, local builds, and appliance OS upgrades remain manual. Never
  run APT on TrueNAS. Never broaden this into host,
  pool, network, account, or guest lifecycle maintenance.

- Use the scoped playbooks under `playbooks/` for custom apps. Inspect their
  own gates before invocation. A `site.yml` tag does not deploy every custom app.
- `playbooks/cloud-backup.yml` configures native encrypted backup tasks and
  preparation scripts. The sequential runner owns the nightly cron schedule.
  Preserve exclusions, 30-version retention, and the initial-success gate.
  See `files/cloud-backup/SETUP.md` and `RESTORE.md` in that directory.
- Appdata preparation now generates a metadata-only media catalog before
  SQLite copies. Keep atomic publication and failure propagation. Media contents
  remain excluded. Catalog restoration does not restore movies or music.
- LANCache uses a dedicated macvlan address, manager worker routing, and a
  fixed private dashboard address. Preserve the local DNS forwarding path and
  network reservations. See `files/lancache/SETUP.md` before any network change.
- FastChannels requires `fastchannels_public_base_url` with an HTTPS origin.
  Threadfin uses the canonical playlist/XMLTV links. Proxy/DNS ownership remains
  in `../proxmox/docs/local-services.md`. TrueNAS API proxy upstreams require TLS.

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

For credential transport or configuration backup changes, run
`python3 tests/test_secret_transport.py`. For backup preparation changes, run
`python3 roles/truenas_cloud_backup/files/test_prepare.py`.
These checks use fixtures, not live appliance state.

For any live change, first use `--check` where the underlying TrueNAS API
operation supports a meaningful check mode. Then apply only the selected tags,
verify services and storage health, and perform a second run expecting
`changed=0`.

Syntax checks use the ignored local inventory and variables. If they have not
been created from the tracked examples, report that prerequisite instead of
weakening inventory, authentication, or host-key checking.
