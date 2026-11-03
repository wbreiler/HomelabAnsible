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
Each request gets **one channel reply**, with a separate section for each host.
The reply starts with **Working…** and updates as hosts finish. Each section
shows measured totals, a short summary, and up to two version comparisons.
An optional thread holds the full host replies, including up to five installed
→ available comparisons. Confirmed comparisons appear before uncertain image changes.
Full normalized evidence stays in the host's private report. PVE/PBS poll
every 10 seconds. TrueNAS polls every minute. Update checks can take 2–5 minutes.

## Coverage

| Target | Update checks | Health checks |
| --- | --- | --- |
| PVE hosts and running LXCs | Refresh APT metadata. Compare catalog apps, native packages, SearXNG commits, Minecraft packs, and all running Docker images with their upstream sources. | Guest power state, root filesystem and memory usage, failed systemd units, reboot flags, host ZFS, and cluster quorum. |
| PBS | Refresh APT metadata and count host/PBS package updates. | Host resources/services, ZFS health, datastore filesystem usage. |
| TrueNAS | Middleware OS availability plus live registry/source comparisons for every running container, including custom apps and sidecars. | Host resources, app states, pool states, active alert classes. |
| Stopped guests and QEMU VMs | Explicitly uninspected. Never start a guest. | Observed power state and missing probes. |

Custom apps are inspected directly. A TrueNAS deployment label such as `1.0.0`
is not used as the installed application version. `app_versions.py` reads image
references, selected OCI labels, and installed digests. Docker Hub uses its tag
metadata API to reduce registry throttling. Other registries use Docker Buildx
to read manifests and image configuration metadata without pulling layers.
Comparisons select the host's platform. Buildx also checks the image configuration
digest. Docker Hub manifest changes are labeled separately from app releases.
If an old pinned index has lost its tag metadata, the report explicitly marks
the platform comparison as unconfirmed instead of claiming a verified update.

Version-pinned images compare against their upstream release channel. Explicit
channels such as `stable-alpine` and `plexpass` stay selected. FastChannels,
Gluetun, and the SABnzbd image use published release tags. If a publisher does not
provide a usable version, the reply identifies the concrete image build by digest.
A different image with the same app version is labeled **image rebuild**. Local
builds use their source revision and upstream release or default branch. Local
patches are preserved; these comparisons never rebuild or deploy an image.

Native LXC probes cover Apt-Cacher NG, Tailscale, Loki, Grafana, SearXNG, and
netboot.xyz alongside the updater's existing catalog. Netboot compares the real
payload hashes, not its Secure Boot shim. Minecraft compares installed file IDs
with stable releases for the configured game version. Modrinth also filters the
loader. CurseForge uses the configured pack project and server-pack type. Manual ATM10
and Better MC imports remain manual, but now get release comparisons. CurseForge
requests run inside the existing credential-bearing guest. Its key never enters
the parent report, process arguments, model input, or Discord.

TrueNAS OS availability remains cached. Source-tracked apps such as SearXNG and
local Cobalt builds report revisions when no release tags exist. Failed probes
name the app and failure category. Application logins, playback, restores, and
complete service paths are not tested. Available versions can require major
upgrades or manual rebuilds; availability is not authorization to install.

No inspection installs packages, downloads image layers or application archives,
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
The shared footer shows the reported model identifiers and total estimated API
cost in USD. It sums the rounded per-host estimates, including cache discounts.
Each thread reply retains its own model and cost. Incomplete requests show a
subtotal. Skipped calls show $0. Missing usage remains explicitly unavailable. See
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

The first configured host coordinates the channel reply. Other hosts publish
their results only inside its details thread. This avoids simultaneous edits
overwriting another host's section. The coordinator refreshes the reply during
its check and subsequent polls. After 20 minutes, missing hosts are marked as
unreported. A missing response never counts as a healthy host. Coordination
uses Discord and needs no cross-host SSH access or additional model call.
The coordinator must be available to begin a combined reply. Its saved state
survives worker restarts. Delivery retries reuse completed results.

## Deployment

The worker reuses `proxmox/.maintenance-repairs-discord.json` and
`proxmox/.maintenance-briefs-openai-key`. Both remain ignored. Each host receives
root-only credentials. No cross-host SSH credential, new API account, inbound
port, or external controller is required.

For combined replies, add `query_nodes` to the ignored bot JSON on the controller,
with the same ordered list on every deployment. The first host is the coordinator.
Names must match the configured inventory names. For example:

```json
"query_nodes": ["pve-a", "pve-b", "backup", "storage"]
```

One to six unique hosts are supported. Omitting the list preserves standalone
host replies. The bot also needs **Create Public Threads** and **Send Messages
in Threads** in the maintenance channel. Existing owner-only routing still
applies. Only the coordinator answers help requests.

From `proxmox/`:

```sh
python3 tests/test_maintenance_queries.py
python3 tests/test_maintenance_query_groups.py
python3 tests/test_app_versions.py
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

### Expanded custom-app checks later that day

The custom-app extension resolved the initial release gaps. Installed workers
completed 22 app entries on Prometheus, 12 on Atlas, and 18 running-container
entries on TrueNAS. These covered all 31 running LXCs and 13 TrueNAS apps.
No app probe failed. Stopped VM 122 remained uninspected.

Examples included Better MC v62 → v62hf, SearXNG 28 commits behind master,
FastChannels 5.6.0 → 5.8.0, and Lidarr 3.1.0.4875-ls43 → 3.1.6.5079-ls46.
Netboot 3.0.3, both ATM10 8.4 packs, and the local Cobalt revisions matched
their checked upstreams. These are dated observations, not current guarantees.
Docker Hub registry throttling prompted the tag metadata probe. Missing old
index metadata remains an explicit platform-comparison limit.

Validation passed 92 maintenance/query tests, 14 app-version tests, and five
cost tests. Both projects passed lint, syntax checks, and deployment dry runs.
Repeat applies reported `changed=0` on all four hosts. Installed source hashes,
private file modes, imports, and Linux timers passed. Linux inspections also
passed with the service's filesystem restrictions and `NoNewPrivileges`.

Labeled update reports reached Discord through the installed workers using
the normal AI counters. Readback confirmed the app comparisons, returned model,
and estimated cost. No owner message or approval reaction was simulated.
Guest states and uptimes, TrueNAS apps/pools, and PBS proxy/pools matched the
protected baseline. No package, image, pack, or application update was installed.

The final display adjustment limits update summaries to 200 characters and
prioritizes confirmed comparisons. It passed repeat deployment and source-hash
checks on all four hosts. PBS initially remained on the preceding display code
because its 1Password SSH agent refused signing. After the owner unlocked
1Password, the scoped PBS dry run, deployment, and repeat apply passed.
The installed PBS renderer passed the 200-character check using saved evidence.
Its bot timer, backup proxy, and pools remained healthy. Verification did not
make another OpenAI request or alter the existing query counters.

### Combined reply rollout later that day

The shared-reply implementation passed 104 maintenance/query tests, including
12 grouping tests, plus 14 app-version tests and five cost tests. Both projects
passed lint and syntax checks. Grouping tests cover one public reply, independent
thread results, retries without repeated inspections or API calls, forged-result
rejection, missing hosts, unknown costs, and newest-result ordering.

A labeled Discord preview used previously saved results. It created one channel
message and four optional thread details. Readback confirmed four host sections
and the aggregated footer. One legacy result lacked cost metadata and remained
explicitly unavailable. This preview made no OpenAI calls or host inspections.

Linux deployment and repeat application passed on both PVE hosts and PBS.
TrueNAS deployment remains blocked by its 1Password SSH signing failure.
Activation is held: the Linux workers retain standalone replies through a
temporary deployment override, so a mixed rollout cannot leave a shared summary
waiting for a legacy TrueNAS reply. The ignored bot JSON retains the intended
ordered `query_nodes` list. After restoring TrueNAS authentication, deploy its
scoped worker first, then rerun the normal Linux playbook without the temporary
override. Verify a new owner mention before claiming the combined path live.
