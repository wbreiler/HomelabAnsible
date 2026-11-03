# Discord health and update queries

Mention **Homelab Repairs** in the dedicated maintenance channel:

```
@Homelab Repairs check for updates
@Homelab Repairs how is the lab doing?
@Homelab Repairs help
```

Only the configured owner's mentions in that channel trigger inspections.
Other users, bots, webhooks, and unmentioned conversations are ignored. Discord
allows bots to read messages mentioning them without Message Content Intent.
Each server posts one reply for itself and its guests. The reply starts with
**Working…** and changes to two short sentences, measured totals, and coverage
gaps. Full normalized evidence stays in the host's private report. PVE/PBS poll
every 10 seconds. TrueNAS polls every minute. Update checks can take 2–5 minutes.

## Coverage

| Target | Update checks | Health checks |
| --- | --- | --- |
| PVE hosts and running LXCs | Refresh APT metadata and count available/held packages. Compare catalog apps with stable releases, including newer major/minor releases. | Guest power state, root filesystem and memory usage, failed systemd units, reboot flags, host ZFS, and cluster quorum. |
| PBS | Refresh APT metadata and count host/PBS package updates. | Host resources/services, ZFS health, datastore filesystem usage. |
| TrueNAS | Supported middleware OS/catalog/image update status. | Host resources, app states, pool states, active alert classes. |
| Stopped guests and QEMU VMs | Explicitly uninspected. Never start a guest. | Observed power state and missing probes. |

TrueNAS reports its cached middleware availability. Custom app versions are
deployment labels, not upstream versions. Pinned custom releases need manual
review. Minecraft packs, SearXNG, and other applications without catalog probes
are named as uncovered. Failed probes mean unknown, not up to date. Application
logins, playback, restores, and complete service paths are not tested.

No inspection installs packages, resolves/downloads application artifacts,
writes release pins, creates backups, changes guest power, or restarts services.
APT metadata and private query state are the only inspection writes. User text
routes to fixed `updates`, `health`, or `help` checks. Neither user text nor model
output becomes a command, URL, or repair authorization. Existing maintenance
reports, schedules, and separate reaction-approved repairs remain independent.

## API and delivery

Each completed host inspection uses one `gpt-4.1-mini` Responses request with
normalized facts, `store: false`, a strict JSON schema, no tools, and at most
300 output tokens. Raw logs, command errors, application configuration, secrets,
and arbitrary user text do not leave the host. Measured details and coverage
limits accompany the AI summary. API failure or the request cap leaves a factual
reply. Stronger models remain reserved for repair proposals and result reviews.
Each reply's footer shows the actual model identifier and its estimated API cost
in USD. The estimate uses returned token usage, including cache discounts.
Skipped calls show $0. Missing usage shows cost unavailable. See
[cost accounting and rates](maintenance-briefs.md#model-and-estimated-cost).

Each host permits 20 checks per UTC day, with one minute between repetitions
of the same check. Health followed by updates is allowed immediately. The
default AI limit is 10 attempted calls per host per UTC day. A four-host request
can therefore use four ordinary-model calls. These counters are separate from
repair budgets. Completed results survive Discord delivery retries without
another check or model request. Interrupted checks require a new request.
First activation ignores historical messages. Requests older than 15 minutes
are ignored. No user text or credentials are stored in query state.

Discord throttling uses its returned `retry_after` delay with bounded retries.
It does not trigger a second OpenAI call or another completed inspection.
See [Discord rate limits](https://docs.discord.com/developers/topics/rate-limits)
and [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Deployment

The worker reuses `proxmox/.maintenance-repairs-discord.json` and
`proxmox/.maintenance-briefs-openai-key`. Both remain ignored. Each host receives
root-only credentials. No cross-host SSH credential, new API account, inbound
port, or external controller is required.

From `proxmox/`:

```sh
python3 tests/test_maintenance_queries.py
python3 tests/test_openai_usage.py
ansible-lint
ansible-playbook maintenance-queries.yml --syntax-check
ansible-playbook maintenance-queries.yml --check --diff
ansible-playbook maintenance-queries.yml
ansible-playbook maintenance-queries.yml  # expect changed=0
```

This dedicated playbook targets `proxmox_cluster:pbs_nodes`. It does not invoke
host maintenance or PBS configuration roles. The Linux worker is
`/usr/local/sbin/homelab-status`, its config is `/etc/homelab-status.json`, its
private state is `/var/lib/homelab-status`, and its timer is `homelab-status.timer`.
Fixed LXC probes need namespace privileges. The service protects `/etc`, `/usr`,
and `/boot` from writes and has a 15-minute timeout. It cannot time out a
separate repair worker.

For TrueNAS, first export a protected configuration backup through its existing
`playbooks/backup.yml`. Then run from `truenas/`:

```sh
ansible-playbook playbooks/maintenance-queries.yml --check --diff
ansible-playbook playbooks/maintenance-queries.yml -e truenas_allow_changes=true
ansible-playbook playbooks/maintenance-queries.yml -e truenas_allow_changes=true
```

The appliance reuses the shared role through its role search path. Private
files live under `/root/homelab-status`. Only the named bot cron job is
reconciled through middleware. `timeout 900` bounds it. Pools, datasets,
networking, SSH, and the Ansible account are outside this playbook's scope.

## Diagnosis

Print normalized evidence without Discord or OpenAI on a PVE/PBS host:

```sh
homelab-status --inspect health
homelab-status --inspect updates
```

On TrueNAS, use `/usr/bin/python3 /root/homelab-status/homelab-status.py
--config /root/homelab-status/config.json --inspect health` as one command.
`last-report.json` holds the last normalized evidence. `state.json` holds the
cursor, counters, pending reply, last result identifiers, and token usage. Do not print the
private configuration, reset budgets, or alter cursors to simulate a request.
Validate real owner mentions after the initial cursor is recorded.

## Validation on November 3, 2026

The owner sent health and update mentions in the dedicated channel. All four
hosts delivered replies. The inspections covered 31 running LXCs, 21 catalog
application probes, PBS, and 13 TrueNAS apps. Stopped VM 122 remained uninspected.
The netboot.xyz release probe could not identify the installed version and
remained unknown. Manual packs and pinned custom apps retained their stated gaps.

The first update request exposed a cooldown shared between health and updates.
The cooldown now applies separately to each check. After that fix, the exact
rejected owner request completed on all hosts without resetting counters or
simulating user messages. Replies were shortened, and Discord 429 handling now
waits for the returned retry delay within bounded retries.

Validation passed 91 maintenance/query tests, five cost tests, six TrueNAS secret
transport tests, both projects' lint checks, syntax checks, and dry runs. Repeat
applications reported `changed=0` on all four hosts. Installed source hashes,
module imports, private file modes, and Linux timer/service status passed.
Guest state and uptime, TrueNAS app/pool state, and PBS proxy/pool state matched
the protected baseline. No inspection installed updates or restarted services.

A labeled Discord cost test summarized PBS's saved update report without a new
host inspection. The API returned `gpt-4.1-mini-2025-04-14`, 240 input tokens,
37 output tokens, and no cached tokens. Its estimated cost was $0.0001552.
Discord confirmed the model and rounded $0.000155 footer. The test consumed
one ordinary-model attempt. Existing repair budgets and incident history were
preserved. Repair cost reporting used mocked responses, including incomplete
output and both cache-write lifetimes. No additional repair was run.
