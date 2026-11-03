# Maintenance failure briefs

`maintenance-briefs.yml` installs a read-only worker on each Proxmox node.
It checks completed `lxc-auto-update.service` and `lxc-app-updates.service`
runs every five minutes. Existing maintenance notifications remain independent.
No new guest, package, remote access credential, or Loki query route is needed.

The worker sends one Discord brief for each failed invocation. After a reported
failure, a successful later invocation sends a maintenance recovery message.
Ordinary successful runs stay quiet. Recovery describes maintenance only and
does not claim that application health or a backup restore was verified.

## OpenAI key

Name the OpenAI project API key **homelab-maintenance-briefs**. Give it permission
to create Responses. Put only the key, without quotes, in the gitignored file
`proxmox/.maintenance-briefs-openai-key`. Keep this file at mode `0600`.
The role reads this file on the Ansible controller and provisions both nodes.
Do not paste the key into chat or a command argument.

Alternatively, set `maintenance_briefs_openai_api_key` in the ignored
`proxmox/group_vars/proxmox_cluster.yml` as an **Ansible Vault encrypted variable**.
That variable takes precedence over the key file. Run from `proxmox/`:

```sh
ansible-vault encrypt_string --prompt --name maintenance_briefs_openai_api_key
```

The command prompts for a Vault password and the API key without echoing the
key. Paste the resulting encrypted YAML block into the ignored group variable
file. Do not put the unencrypted key in a command argument, chat, or tracked file.

Use these non-secret settings in that same file:

```yaml
install_maintenance_briefs: true
maintenance_briefs_enabled: true
maintenance_briefs_model: gpt-4.1-mini
maintenance_briefs_daily_call_limit: 10
```

The default Discord destination reuses `lxc_update_discord_webhook_url`.
Set `maintenance_briefs_discord_webhook_url` in ignored/Vault variables only
when a separate destination is required. Each host stores the rendered key and
webhook in `/etc/homelab-maintenance-briefs.json`, owned by root with mode `0600`.
Ansible suppresses the credential task output and diff.

An absent key is supported: failed maintenance still produces a factual brief,
clearly labeled **OpenAI key not configured**. Adding a key does not replay runs
that were already reported. A failed OpenAI request also falls back to facts.

## Deploy and validate

```sh
ansible-playbook maintenance-briefs.yml --check --diff
ansible-playbook maintenance-briefs.yml
ansible-playbook maintenance-briefs.yml
```

The second application should report `changed=0`. Add `--ask-vault-pass` when
the selected local variables contain Vault-encrypted values.
The dedicated playbook touches only the brief and optional repair workers and
their configuration. It does not start an updater during deployment.
The `maintenance_briefs` tag also integrates the role into `site.yml` when
`install_maintenance_briefs` is true.

Run these commands **on a Proxmox node**:

```sh
# Read selected current evidence without API calls, messages, or state writes.
/usr/local/sbin/maintenance-briefs --preview

# Send one clearly labeled synthetic Discord example. No OpenAI call or update.
/usr/local/sbin/maintenance-briefs --test-discord

# Inspect the scheduled worker.
systemctl status maintenance-briefs.timer
journalctl -u maintenance-briefs.service -n 40
```

## Evidence and limits

The worker reads the two updater `last-run.json` files and checks their invocation
IDs against systemd. It skips running units and discards evidence when a unit
changes during collection. A stale or missing report cannot establish success.
It reads at most the last 200 journal entries for the exact invocation.

Only recognized, normalized failure signals leave the host. These include the
backup prerequisite, container/package locks, new failed services, disk space,
DNS, APT signatures/dependencies, TLS verification, and application health checks.
Raw journal text, arbitrary exception reasons, URLs, and application configuration
are never sent to OpenAI or Discord. Unknown failures direct the operator to the
local journal. A broad signal can describe one command rather than the whole run.
The model receives guest IDs, node, job, completion time, status, and these signals.
It has no tools and cannot execute its suggested check.

OpenAI uses the Responses API with `store: false`, a fixed response schema, and
a maximum of 700 output tokens. The daily limit applies to attempted requests
per node per UTC day, including failed requests. Successful maintenance and
Discord delivery retries do not call OpenAI. This is a request cap, not a dollar
cap; model pricing determines cost. No OpenAI request retries occur within a run.

History and a pending Discord payload live in the root-only
`/var/lib/homelab-maintenance-briefs/` directory. Delivery requires Discord to
return a message ID. Failed delivery preserves the payload and retries with a
five-minute delay that grows to one hour. A pending delivery postpones new
collection on that node. Ambiguous network failures can produce a duplicate
message because Discord webhooks do not provide an idempotency key.

The service runs as root to read existing private reports and journals. Systemd
makes the filesystem read-only except for its own state and private temporary
directory, removes capabilities, and restricts device/kernel access. The worker
executes only fixed `systemctl show` and `journalctl` reads. It never calls an
updater, repairs a guest, changes infrastructure, or runs generated commands.

This first version does not collect application reachability, PBS task details,
TrueNAS failures, Minecraft logs, or incidents unrelated to maintenance. It
observes the latest completed invocation, so runs overwritten while the worker
is stopped or waiting for Discord may be missed. Add event capture only if that
limit matters in actual use.

## Local tests

```sh
python3 tests/test_maintenance_briefs.py
ansible-lint
ansible-playbook maintenance-briefs.yml --syntax-check
ansible-playbook site.yml --syntax-check
git diff --check
```

Tests use fake HTTP responses and temporary state. They cover report freshness,
run races, secret exclusion, successful-run silence, failure/recovery delivery,
request limits, fallback behavior, delivery backoff, and redirect rejection.
They do not substitute for a live OpenAI request with the user's key.

On 2026-11-03, deployment and a repeat application passed on Prometheus and Atlas
with `changed=0` on the repeat. Both sandboxed services completed successfully.
One synthetic OpenAI request and confirmed Discord delivery passed on each node.
The tests preserved real incident history and did not run maintenance or induce
a real failure. Neither key copy was tracked. The temporary key copy was removed
after transfer.

## Interactive repair approval

The optional Discord bot adds a separate approval workflow. The brief worker
remains read-only. No public callback endpoint or privileged Discord intent is
required. The controller polls normal message reactions about every 10 seconds
while idle. An API request or another in-progress analysis can delay the next poll.

1. React 🔍 on a failure brief to request a stronger-model proposal.
2. Read the target, fixed operation, side effects, reason, and uncertainty.
3. React ✅ on that proposal to authorize one attempt, or ❌ to decline.
4. Read the result and the stronger-model review in the same channel.

A single status reply acknowledges the request and updates through **Working…**
(preparing the proposal), **Waiting for your approval**, **Working…** (approval
received, running the attempt, then reviewing the result), and **Finished**.
Each update includes its timestamp. Long backups retain the running stage until
the attempt ends. Declines, expiry, errors, and detected interruptions also clear
an existing working indicator. The final result remains a separate message.

Status updates do not call OpenAI. The bot edits its status reply and preserves
the proposal text used to validate consent. Notification failures do not interrupt
an approved package transaction. A later stage or controller poll retries status
delivery. A host or Discord outage can delay updates, so check the displayed time.

Only the configured owner's Discord user ID counts. Other users and bots cannot
request analysis or approve an attempt. Requests expire after 24 hours. Proposals
expire after 30 minutes. Approval applies to that exact displayed proposal,
target, code, configuration, and maintenance report. Changed or stale inputs
cancel execution. Approvals are consumed before any mutation and cannot replay.
Changing the channel requires new requests. This version permits one proposal
and at most one attempt per failed invocation. It does not reopen closed requests.
A new failed maintenance invocation can offer a new proposal and requires new consent.

Initial supported operations are targeted retries through the existing updaters:

| Operation | Scope and guards |
| --- | --- |
| OS retry | One running local guest, recent usable backup, holds, no package removals, and failed-service comparison. |
| Backup and OS retry | Fresh PBS snapshot backup of that guest, then the same OS guards. Backup failure stops the attempt. |
| Application retry | One configured catalog app on one running guest. Explicit failed-update retry, fresh PBS backup, compatible stable release, release age, checksums, and health checks remain required. |

Services inside the selected guest can restart. This is a bounded retry system,
not a general remote shell. The model selects an operation from a fixed schema.
It cannot generate executable commands. Unsupported or ambiguous failures require
manual investigation. Package-target application batches, host changes, guest
power/hardware, storage/network/SSH changes, restore, and major upgrades are not
available. The application updater can refuse a retry when no eligible newer
release exists. No infrastructure action runs simply because analysis recommends it.

The executor shares the scheduled updaters' lock. Busy maintenance stops the
attempt without automatic retry. It writes separate repair results and preserves
the scheduled `last-run.json` reports. A successful retry does not itself rewrite
the scheduled failure into a recovery. Interrupted attempts never repeat and
require local investigation. Active package transactions have no service timeout.

### Bot credentials

Create a Discord application and bot named **Homelab Repairs**. Install it into
the server containing the webhook's channel. Grant View Channel, Send Messages,
Embed Links, Read Message History, and Add Reactions for that channel. Restrict
its access to this channel. Do not grant Administrator or privileged intents.
Enable Discord Developer Mode and copy your own user ID.

Keep this JSON in the ignored `proxmox/.maintenance-repairs-discord.json`, mode
`0600`. Use strings for all Discord IDs. Never paste the token into chat or argv.

```json
{
  "bot_token": "REPLACE_PRIVATELY",
  "owner_user_id": "YOUR_DISCORD_USER_ID",
  "channel_id": "WEBHOOK_CHANNEL_ID",
  "bot_user_id": "BOT_USER_ID"
}
```

Verify the bot identity with Discord's `GET /users/@me` and its access to
`GET /channels/{channel_id}`. The channel must match the dedicated webhook.
The role stores these values in `/etc/homelab-maintenance-repairs.json`, root
`0600`, with secret output and diffs suppressed. The existing OpenAI key is reused.
Set these non-secret values in ignored group variables:

```yaml
maintenance_briefs_repairs_enabled: true
maintenance_briefs_repairs_model: gpt-6.1-sol
maintenance_briefs_repairs_daily_call_limit: 2
```

Deploy with the same check/apply/repeat commands above. The controller timer is
`maintenance-repairs.timer`. The privileged `maintenance-repair-execute.service`
has no timer, automatic restart, or boot enablement. Only an approved request
starts it. The controller has a read-only filesystem except for its own state.
The executor needs the existing updaters' host privileges and is constrained by
its fixed operation catalog and approval checks, not a filesystem sandbox.

Set `maintenance_briefs_repairs_enabled: false` and redeploy to disable polling
and reject new execution. This does not kill an already running transaction.

### Stronger-model use and cost limits

Planning and result review use `gpt-6.1-sol` with high reasoning, structured
Responses output, `store: false`, and at most 6,000 output tokens per request.
`gpt-6-astra` is an explicit configuration alternative. Availability depends on
the OpenAI project. Ordinary failure briefs continue to use `gpt-4.1-mini`.

At most two stronger-model requests are attempted per node per UTC day. Planning
and review share that cap, including failures. Thus one normal proposal-plus-review
can use a node's entire daily budget. If review cannot run, the factual result
still posts. No automatic API retry or extra repair attempt occurs. This is a
request cap, not a guaranteed dollar cap. Input is limited to 20,000 characters.

Only normalized evidence, candidate operation metadata, a fixed result summary,
and allowlisted failure signals from the final 100 KB of repair output reach
OpenAI. Raw updater output stays in private local repair logs.
The model has no tools or direct host access.

### Interactive validation

Run `python3 tests/test_maintenance_repairs.py` beside the brief tests. These
cover owner checks, altered/expired/replayed approval, stale evidence, crashes,
maintenance concurrency, API caps, one-guest dispatch, and backup failure guards.

On one node, run `/usr/local/sbin/maintenance-repairs --test-interaction`. This
posts a clearly labeled test. React 🔍 and then ✅ on its proposal. The stronger
model makes real API calls, but the only permitted test operation is a no-op.
This validates Discord consent and the executor without running maintenance.

State, private logs, and the API counter live in
`/var/lib/homelab-maintenance-repairs/`, root `0700`. Inspect controller errors
with `journalctl -u maintenance-repairs.service -n 40`. Never publish raw logs.
Discord message retries use a stable nonce. Discord's short nonce window does
not guarantee deduplication after a long ambiguous outage. Duplicate messages
cannot grant a second execution because authorization belongs to one local record.

On 2026-11-03, the interactive workers were installed on both nodes with repairs
disabled while Discord bot installation was pending. Check mode, repeat application
(`changed=0`), unit validation, private permissions, and refusal of disabled
execution passed. All 96 related local tests passed. The 27 approval tests also
passed against the installed code on each Linux node with mocked external actions.
A real synthetic `gpt-6.1-sol` high-reasoning structured request succeeded.
At that stage, the Discord owner-reaction round trip and a real repair were untested.

Later on 2026-11-03, the bot joined the server and access to the dedicated
`homelab-maintenance-briefs` channel was verified. Interactive repair polling was
enabled on Prometheus and Atlas. The activation check passed, repeat application
reported `changed=0` on both nodes, and both deployed bot credentials could read
the channel. Controller services completed successfully and private credential
permissions remained `0600`.

The owner subsequently completed the live no-op test on Prometheus. The bot
recognized the owner's 🔍, generated a `gpt-6.1-sol` proposal with high reasoning,
accepted the owner's ✅ on that separate proposal, and started the one-shot
executor. The executor succeeded without infrastructure actions. The stronger-model
result review and final Discord delivery also completed. The closed incident
retained the owner approval and successful no-op result. This used Prometheus's
two stronger-model requests for the UTC day. No real maintenance repair was tested.

Progress indicators were then deployed on both nodes. All 59 focused local tests
passed, including the 35 repair tests also run against each installed Linux worker
with external actions mocked. Lint, syntax, check mode, timer validation, and
repeat deployment (`changed=0`) passed. A labeled Discord display test updated
one reply through all six stages and verified the final content. It used temporary
state, left the OpenAI request counter unchanged, and performed no real repair.

## Real repair drill on the disposable pilot

The manual `maintenance-repair-drill.service` checks a backup prerequisite on
the existing Terraform-owned `terraform-pilot` LXC. It has no timer and cannot
create, start, stop, or delete a guest. Before enabling it, inspect the pilot
for unexpected application workloads or data. The runner requires the configured
VMID to be local, running, unprivileged, named `terraform-pilot`, unlocked, and
free of external mounts or device passthrough. Ordinary updater exclusions apply.

Set `maintenance_briefs_drill_vmid` to that VMID in the owning node's ignored
host variables, then deploy `maintenance-briefs.yml`. Zero disables the drill.
Run `systemctl start maintenance-repair-drill.service` on that node. Its expected
failure means no usable backup meets the drill's stricter 15-minute requirement.
It only reads metadata and writes its own report. It preserves existing backups,
normal updater settings, and scheduled maintenance reports and journals.

The brief is labeled **DRILL · Test container only**. React 🔍 to request a
stronger-model proposal, then ✅ on that separate proposal. The only repair
candidate is a fresh PBS snapshot followed by the existing guarded OS updater
for the configured pilot alone. The executor rechecks the pilot identity and
uses the stricter freshness requirement only for this attempt. This is a real
backup and package-maintenance operation, not the synthetic no-op test.

The test container's services can restart. Other guests are never update targets.
The small snapshot adds ordinary backup I/O to the shared hosts and PBS.
After the attempt finishes, rerun the read-only drill check while the backup is
still fresh. A passing check clears the drill failure and produces its recovery
brief. The report stays in `/var/lib/homelab-maintenance-repairs/drill-report.json`.
No guest lifecycle or Terraform resource change is required for this workflow.
The brief service orders itself after the drill. This retains the completed
drill's systemd invocation without starting it automatically. Without that
reference, systemd unloads a successful manual unit before recovery collection.
See the [systemd unit retention rules](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html#Unit%20Garbage%20Collection).

On 2026-11-03, live inspection found only baseline operating-system services in
Atlas's existing pilot, with no external mounts or failed services. The drill
deployment passed 67 focused local tests, 41 mocked repair tests on each node,
lint, syntax/check mode, and an idempotent repeat application. Its initial
read-only check failed the 15-minute freshness rule as expected and delivered
a labeled Discord brief. Guest uptime, packages, normal updater configuration,
scheduled reports, and backup metadata were captured privately for comparison
after the owner-approved repair.

The owner then requested and approved the real drill repair in Discord. Atlas
used `gpt-6.1-sol` with high reasoning for the proposal and result review. The
executor created one new PBS snapshot for CT 114 and completed guarded OS
maintenance for that guest alone. No packages needed changes. Baseline comparison
confirmed that all older pilot backups remained, other guests had no status or
reboot changes, and the pilot had no reboot or newly failed services. Normal
updater configurations, scheduled reports, and maintenance invocation IDs stayed
unchanged.

The subsequent read-only backup check passed. This exposed a missing systemd
ordering reference that allowed the successful manual unit's invocation to be
unloaded. The reference was added, deployed, and verified against the retained
invocation and delivered recovery brief. Proposal, final progress, and result
messages also matched their recorded content. The fix passed all 67 focused
tests, lint, syntax/check mode, and repeat application with `changed=0` on both
nodes. No second repair or extra stronger-model request was needed.

This validates an owner-approved backup-prerequisite repair and OS retry on the
pilot. It does not validate package replacement, application repair, rollback,
backup restoration, or every service's application-level health.
