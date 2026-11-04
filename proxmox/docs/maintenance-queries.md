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

## Initiate an app update

```text
@Homelab Repairs update sonarr on atlas
@Homelab Repairs update lidarr on erebus
@Homelab Repairs update deluge/gluetun on erebus
```

Use the host and app/service name from the update report. These examples are
command syntax, not verified placement or authorization to install anything.
An explicit `update APP on HOST` request prepares a proposal on that host only.
Review its version, backup requirement, and restart scope. React **✅** to
authorize one attempt, or **❌** to cancel. Approval expires after 30 minutes.
The bot edits **one message** from Working to approval, execution, and result.
Missing host names and shell syntax never become installations. Use the batch
commands below for multiple targets.

The fixed adapters select the target. Routine update requests need no model:
their footer reports **Model: none · API cost: $0.000000**. Stronger-model repair
proposals and reviews remain separate. Update requests do not consume ordinary
inspection or AI budgets.

Supported execution paths:

| Target | Behavior |
| --- | --- |
| Apps enabled in the existing LXC role/native catalog | Resolve exact artifacts, preserve the configured compatible-release and age guards, create a fresh PBS backup, run one existing installer, and verify its result. |
| TrueNAS custom apps with running registry images | Select one verified stable image in the same release line. Pin its platform digest and all unchanged sidecar images. Save the original configuration privately, require a successful system/settings/appdata backup within 30 hours, then redeploy only that app through `app.update`. |
| Multiple newer images in one TrueNAS app | Require `APP/SERVICE` to select one image. The complete app and its sidecars can restart. |
| Catalog apps, locally built images, Minecraft packs, source-only apps, netboot Secure Boot, or major upgrades | Explain the unsupported case and require the owning playbook or TrueNAS upgrade screen. Never invent an installer or replace local patches. |

TrueNAS checks the resulting configuration, exact image identities, RUNNING
state, and available container health checks. It blocks Tdarr during active
transcodes or when its process check fails. The check includes Docker's required
PID column and examines process names in every app container. It does not prove
logins, playback, database recovery, or full user
workflows. Its backup can precede the update by up to 30 hours; recovery can
lose later changes. There is no automatic retry or rollback. The original
Compose configuration is a configuration copy, not a fresh application-data
backup. The adapter uses the supported
[TrueNAS app.update API](https://api.truenas.com/v25.10/api_methods_app.update.html).

The executor verifies the owner reaction, exact displayed proposal, expiry,
target hash, code/configuration hash, current guest/app identity, and existing
maintenance lock. It persists approval consumption before any mutation.
Preparation compares implementation hashes before and after resolving a plan.
A changed implementation requires a new proposal. If ✅ arrives before the
proposal is ready, the bot explains how to remove it, review, and approve again.
The executor preserves the controller's current delivery state under the lock.
Progress and final results cannot overwrite another request or forget that the
approval message was deleted. RC, pre-release, and preview tags are excluded
from TrueNAS stable-image proposals, including dotted forms such as `-rc.1`.
Interrupted execution never repeats. Each host permits one active app update
request. The executor runs as a separate transient `homelab-app-update.service`
without a restart policy or execution timeout; query timeouts cannot kill an
approved package transaction. It does not change guest hardware or power,
storage datasets, networking, SSH, or accounts.

`app-update.json`, archived `app-update-REQUEST.json`, and per-request logs stay
root-only in the existing query state directory. They can contain app secrets.
Never print or publish their contents. No new credentials are required.

Validation on 2026-11-03: 164 focused tests, both project lint/syntax checks,
dry runs, deployments, and repeat runs passed. All four hosts matched the
source hashes and returned `changed=0`. Both execution platforms started with
isolated empty approval state and performed no action. A real owner request
produced one Lidarr proposal; the owner's cancellation closed it without
changing its configuration or image. No approved installation was performed
as part of this validation. Guest uptime and storage/service baselines remained
unchanged. These results are dated evidence, not a current health guarantee.

## Update a host or the homelab

```text
@Homelab Repairs update apps on atlas
@Homelab Repairs update os on atlas
@Homelab Repairs update all on atlas
@Homelab Repairs update all on erebus
@Homelab Repairs update the homelab
```

`update all on HOST` and `update the homelab` prepare **applications and OS packages**.
The two scoped commands select one category:

| Command | Selected actions |
| --- | --- |
| `update apps on HOST` | Guarded LXC role/native apps, eligible managed held app packages, or supported TrueNAS custom images. |
| `update os on HOST` | Exact APT updates on the PVE/PBS host and eligible running LXCs on that host. Existing holds remain active. |

App installers can still install or update their required dependencies. Apps-only
requests skip general OS upgrades and host APT planning. They can refresh guest
APT metadata for managed app package comparisons. OS-only requests skip app
release probes and guarded app installers. Ordinary APT updates can include
distribution-packaged services, while managed app package holds stay in place.
`update os on erebus` explains that TrueNAS needs its separate appliance upgrade
workflow. `update apps on mnemosyne` directs the user to its OS package workflow.
These unsupported combinations produce no actions or approval request.

All these commands prepare plans. They do not authorize
installation. The bot edits one channel message through preparation, approval,
execution, and completion. Each host attaches its exact version plan inside
that message's thread. Review those plans and their exclusions before reacting
**✅**. React **❌** to cancel. An early approval must be removed and added again
after the proposal appears.
The scope appears in the channel summary and each attached plan. The approval
binds that scope to the exact actions. Changing the scope or adding an action
from another category prevents execution and requires a new proposal.

| Scope | Included | Explicit exclusions |
| --- | --- | --- |
| PVE host | Exact APT upgrades, after local guest work | Package removals, held host packages, reboots |
| Running LXCs | Exact APT upgrades, eligible managed app packages, existing guarded role/native installers | Excluded/stopped guests, unsupported custom installers, Minecraft packs, Secure Boot replacement, incompatible/young releases |
| PBS host | Exact APT upgrades | Removals, held packages, reboots |
| TrueNAS | Eligible custom apps, with all reviewed image changes combined into one redeploy per app | Appliance OS, catalog apps, local builds, unsupported release lines |
| QEMU guests | Report their exclusion | No guest OS/app executor configured |

Each app retains its existing compatibility, release-age, backup, and health
checks. APT plans list every simulated version change, including new dependencies.
APT automatic/manual retention flags remain separate for each architecture.
An automatic `:i386` dependency cannot mark a manual `:amd64` package automatic.
Execution rejects changed installed versions, dependencies, holds, or new failed
services. Guest package actions require a fresh PBS backup. PVE/PBS host actions
require healthy platform services, PVE quorum where applicable, and no active
platform tasks. They save `/etc` and the dpkg status privately before installation.
This host copy is **not a full system backup**. Package scripts can restart services.
The bot reports reboot requirements but never reboots automatically.

Fleet scope follows the configured `query_nodes` order. Every selected host must
publish a plan before approval becomes available. Unavailable individual checks
remain visible as exclusions. A proposal expires after 30 minutes. Approval
binds all plans and opens a six-hour execution window. Hosts and local actions
run sequentially. A failure stops all remaining actions. Cancellation or removal
of ✅ stops pending work after the current transaction. No automatic retry or
rollback occurs. Request a fresh plan after inspecting a failure.
Cancellation before approval marks prepared hosts as not started. After approval,
stale host observations remain labeled as last reported until a terminal result
arrives. Failed final-result delivery is retried before closing local batch state.
Delivery retries never repeat an update.

Preparation and execution use separate transient `homelab-batch-prepare` and
`homelab-batch-execute` services. Query timeouts cannot terminate an approved
package transaction. The bot consumes each action before execution and never
replays an interrupted batch. Implementation, configuration, target hashes,
owner reactions, and the visible summary are rechecked before each action.
Batch and single-app requests cannot overlap on one host.

Public `maintenance-plan-HOST.txt` and `maintenance-result-HOST.txt` attachments
contain selected versions, effects, exclusions, and results. Private
`maintenance-batch.json`, `batch-REQUEST.json`, and per-request directories/logs
remain root-only. They can contain app configuration and secrets. Never publish
them. The batch uses no model and costs **$0 in OpenAI API usage**.

Read-only preparation checks at most three guests/apps concurrently and retains
stable plan order and per-target exclusions. TrueNAS scans Docker once per
batch, compares images three at a time, and reuses those observations only
within that preparation. Runtime execution still rechecks live configuration,
image identities, approved versions, and owner authorization before each action.
Ordinary release reports also use parallel catalog checks and bulk
[formatted Docker inspection](https://docs.docker.com/reference/cli/docker/inspect/).
Each report clears its upstream metadata cache first.
Apps missing from the running-container inventory remain visible as unavailable.
Batch plans exclude stopped apps, missing images, and unavailable/manual checks
explicitly. These exclusions do not count as evidence that an app is current.
No approval or installation is cached or parallelized.

TrueNAS retains its minute cron entry. Each invocation holds the existing
exclusive worker lock and polls Discord about every ten seconds for up to
50 seconds. A long inspection can finish beyond that window. Overlapping cron
invocations exit without replay. Linux continues to use its ten-second timer.

For a safe live delivery test, send a batch command, review its proposal, and
react **❌**. Do not react ✅ unless the listed real updates are authorized.

Batch validation on 2026-11-03: 185 focused tests passed, including a simulated
two-host approval and sequential execution. Both project lint/syntax checks and
deployment dry runs passed. All four deployed hosts matched the source hashes
and file permissions. Repeat runs returned `changed=0`. Guest uptime, NAS
app/pool states, PBS health, and API counters remained unchanged. A live PBS
plan resolved nine package upgrades without installing them. The real owner
fleet command produced one channel reply and four exact plan attachments.
Each attachment matched its host's prepared manifest. The proposal covered
37 OS packages and six apps, with exclusions recorded separately. The owner's
❌ closed the batch on all four hosts. Every executor remained inactive, with
no action started. All planned package versions, app versions/configuration,
and NAS image identities remained unchanged. API counters and service baselines
also matched. No real batch installation was tested.

Performance validation on 2026-11-03 measured complete read-only plan preparation
on the two slowest hosts. Prometheus improved from 187.53 to 85.71 seconds (54%).
TrueNAS improved from 68.72 to 27.52 seconds (60%). Proposed actions and sorted
notices matched the earlier owner-reviewed plans. TrueNAS inventory calls fell
from 19 to one per batch. Bulk inspection returned identical metadata for all
18 containers and a single-container case. These are worker timings from one
before/after sample, excluding Discord delivery. Upstream latency can vary.
Ordinary update collection then completed in 54.0 seconds on Prometheus,
29.8 on Atlas, 12.8 on TrueNAS, and 1.0 on PBS, with no unavailable app probes.
Those measurements exclude AI summaries and Discord delivery. All 191 focused
tests, both project lint/syntax checks, deployment dry runs, and live source
verification passed. All four repeat deployments returned `changed=0`.
Guest uptime and NAS/PBS service baselines remained unchanged. No app or OS
updates ran during performance validation.

Bug-fix validation on 2026-11-03: 197 focused tests passed. New regressions
cover absent/stopped NAS containers, unavailable/manual image checks, canceled
summary labels, final-delivery retries, and diagnostics under an occupied lock.
Both project lint/syntax checks and deployment previews passed. All four hosts
matched deployed source hashes and private modes, with repeat `changed=0`.
Live TrueNAS `--inspect health` and `--inspect updates` returned evidence in
1.7 and 12.9 seconds while the existing worker held its lock. API budgets and
the cursor stayed unchanged. Guest uptime, NAS app/pool states, and PBS health
matched the baseline. Discord failures were simulated in tests. No new owner
reaction round trip or real app/OS installation was performed for these fixes.

Recovery review on 2026-11-04: 206 focused tests passed. Regression tests first
reproduced deleted-reply queue blocking, missing-thread waits, stale executor
delivery state, unexplained early approvals, implementation drift during plan
preparation, cross-architecture APT retention changes, and accepted prerelease
image tags. Tests also verify that an executor cannot overwrite a different
request, valid stable image suffixes remain eligible, and transient delivery
errors still retry without another inspection or API call.
Both project lint/syntax checks, scoped previews, and deployments passed.
All four hosts matched source hashes and private modes. Repeat deployments
returned `changed=0`. Fresh service baselines and API counters stayed unchanged,
with all update executors inactive. Execution and Discord failure cases used
isolated tests. No real update or new owner-reaction round trip was performed.

Scope selection validation on 2026-11-04: 216 focused tests passed, including
approval and cancellation for both new selectors, scope tampering, host routing,
and unsupported platform/scope combinations. Both project lint/syntax checks
and deployment previews passed. All four deployed hosts matched source hashes
and private modes, and repeat deployments returned `changed=0`.
Live preparation produced only app actions for `apps` and only APT actions for
`os`, with no unavailable checks. Prometheus prepared two app actions and 103
OS package versions, Atlas one app action and 69 package versions, PBS 12 package
versions, and TrueNAS five custom-app actions. PBS apps and TrueNAS OS requests
returned their explicit exclusions without probing the other category.
These were read-only plans, not installations. No backup or executor started.
Guest uptime, NAS app/pool states, PBS health, query cursors, and API counters
remained unchanged during read-only preparation. The owner then tested
`update apps on erebus` and `update os on mnemosyne` through Discord. Each
command produced one channel reply with the correct scope. Both attached plans
matched their private prepared manifests. The owner's ❌ closed both requests,
with no action started, no execution results, and both executors inactive.
The service baseline still matched after cancellation. No real installation
was performed as part of this validation.

Tdarr process-check correction on 2026-11-04: a later owner-approved app batch
updated FastChannels and Lidarr, then stopped before changing Tdarr. Docker
rejected the process-name-only check because its output omitted the required
PID column. Deluge and spotDL were not attempted. The shared adapter now includes
PID and process name, preserves the active-transcode guard, and rejects empty or
malformed process rows. All 217 focused tests passed, including idle Tdarr,
ffmpeg/HandBrakeCLI in another app service, and failed or incomplete probes.
Both project lint/syntax checks and deployment previews passed. Installed hashes
and private modes matched on all four hosts; repeat deployments returned
`changed=0`. The deployed Tdarr preflight reached the mutation boundary with `app.update` blocked by the
test. Fresh reads verified both completed updates and the original images and
configuration of all three unfinished apps. All 13 apps were RUNNING and pools
were healthy. The failed batch remained closed and was not replayed. A new
proposal and owner approval are required for another update attempt.

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
Deleting a report reply or details thread ends that delivery attempt and frees
the queue for later requests. It does not repeat the inspection or model call.
A missing details thread expires after 20 minutes even if its parent summary
was already created. Transient network/API errors still retain saved replies
for retry.
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
host replies. The bot also needs **Create Public Threads**, **Send Messages
in Threads**, and **Attach Files** in the maintenance channel. Existing owner-only routing still
applies. Only the coordinator answers help requests.

From `proxmox/`:

```sh
python3 tests/test_maintenance_queries.py
python3 tests/test_maintenance_query_groups.py
python3 tests/test_maintenance_batches.py
python3 tests/test_app_versions.py
python3 tests/test_app_update_requests.py
python3 tests/test_lxc_app_updates.py
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

The dedicated Linux and TrueNAS query playbooks enable
`maintenance_queries_app_updates_enabled`. The shared role defaults this gate
to false. Enabling it on PVE also installs the approval-aware existing app
updater; its catalog/configuration must already exist. Deployment does not
initiate an app update. A new owner command and proposal reaction are required.

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
Direct inspections bypass the polling-state lock, so an idle cron worker cannot
silently suppress their output. They do not change query state or API counters.
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

TrueNAS initially could not authenticate through its 1Password SSH agent.
Activation stayed on hold with standalone replies until the owner unlocked it.
The scoped TrueNAS deployment then passed, followed by Linux activation without
the temporary override. Repeat applications reported `changed=0` on all four
hosts. Installed source hashes, private file modes, shared host order, and Linux
bot services passed verification. Guest state/uptime, TrueNAS apps/pools, and
PBS proxy/pools matched the protected baseline.

The owner then sent a new health mention. It produced exactly one public bot
reply with four host sections and four optional detail messages in its thread.
The shared reply progressed from 1/4 through 3/4 to 4/4 reported hosts.
Readback confirmed the returned `gpt-4.1-mini-2025-04-14` model and a total
estimated cost of $0.001688, matching the four per-host usage records within
display rounding. Each host consumed one normal-model attempt. Aggregation
made no additional OpenAI call. All jobs and summary tracking completed.
The final renderer shortens summaries at word boundaries and preserves the
complete per-host details in the thread. No fresh update scan or repair was
needed for this delivery change.
