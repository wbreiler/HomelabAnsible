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
The dedicated playbook touches only the brief worker and its own configuration.
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
