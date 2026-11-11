# Ask the lab with Netdata

Netdata collects local measurements. The existing Open WebUI uses the OpenAI
Responses API to interpret selected measurements when the owner asks a question.
There is no Discord worker, repair workflow, or scheduled AI request.
[Application health and filtered logs](app-observer.md) provide additional
read-only evidence through fixed observation tools.

Select **Ask the lab · GPT-6.1 Sol** in Open WebUI. Start with one question:

- How is the lab doing right now?
- Which hosts or containers are under resource pressure?
- What changed in the last hour compared with the previous hour?

The native chat interface shows tool activity and streams the answer. Historical
comparisons require retained measurements. A new collector has no older baseline.

## Components and scope

`netdata.yml` configures only the explicit `netdata_nodes` inventory group.
It does not run from `site.yml` or provision guests. The parent runs alongside
Loki/Grafana in an existing guest. Three children collect PVE and PBS metrics.
The separate [TrueNAS playbook](../../truenas/playbooks/netdata.yml) adds one
custom application without replacing appliance reporting.

The Linux agent is Netdata **2.12.3**, installed from a checksum-verified static
artifact. The TrueNAS image has an immutable digest. Bump the version and pin
together. The installer does not enable its automatic updater.

Collection uses five-second intervals. Children use RAM storage. The parent has
two disk tiers, each capped at 2 GiB. Their time limits are one day and seven days.
Size limits can reduce actual retention. Netdata Cloud and telemetry are disabled.
No outbound notification destination is configured. Existing maintenance and
backup schedules remain separate.

| Component | Access |
| --- | --- |
| OpenAI model | Ten Netdata tools for nodes, metrics, comparisons, and alerts |
| Open WebUI | Private admin-owned model and tool connection, OpenAI credential stored in its existing configuration |
| Linux collectors | Local system statistics through Netdata and its privileged collector helpers |
| TrueNAS collector | Host PID namespace, selected capabilities, read-only host mounts, Docker socket for container discovery |
| Netdata parent dashboard | Explicit private network sources, no public listener or Cloud claim |
| Parent MCP endpoint | Loopback and the explicitly configured Open WebUI address |

The model has no SSH credentials, update commands, shell tool, or repair tool.
Its Netdata allowlist excludes `execute_function` and function discovery.
Separate app observers expose bounded, filtered diagnostic excerpts. Built-in WebUI tools are disabled for this model.
The allowlist is enforced by Open WebUI. An administrator can change it.

The Docker socket remains a privileged interface. A `:ro` bind mount does not
make Docker API operations read-only. It is available to the trusted Netdata
collector, not to the model's tool interface. The container does not use
`privileged: true` or `SYS_ADMIN`.

Host-side cgroup collection includes LXC, QEMU, and Docker resource usage.
It does not establish application functionality, backup success, available
updates, or internal VM health. No agent is installed inside every guest.
Application-specific observers have separate configuration and credentials.
See their [coverage and permission boundaries](app-observer.md).
Never interpret absent measurements as proof of an outage.

Questions, relevant metric results, labels, and selected filtered app diagnostics
go to OpenAI. The request uses
`store: false`. Open WebUI retains the chat locally. This setting is not a claim
of zero provider retention. The OpenAI key and streaming key stay out of prompts.

## Linux deployment

Run from `proxmox/`. Reuse the existing SSH control sockets.

```sh
cp .netdata-inventory.yml.example .netdata-inventory.yml
chmod 600 .netdata-inventory.yml
python3 - <<'PY'
import os, uuid
with os.fdopen(os.open('.netdata-stream-key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as out:
    out.write(str(uuid.uuid4()) + '\n')
PY
```

Edit the private inventory. Match existing host aliases and the actual source
address used by each child. The NAS storage interface can be its source even
when SSH uses its management interface. Never regenerate an existing key during
routine convergence.

```sh
ansible-playbook -i inventory.yml -i .netdata-inventory.yml netdata.yml --check --diff
ansible-playbook -i inventory.yml -i .netdata-inventory.yml netdata.yml
ansible-playbook -i inventory.yml -i .netdata-inventory.yml netdata.yml
```

The repeat run must report `changed=0`. Static agents live under `/opt/netdata`.
The role refuses to replace a distribution-managed agent. Children bind only to
loopback. The parent binds to loopback and its selected private address.
Streaming uses a shared private UUID and explicit source restrictions. This
version uses HTTP and unencrypted streaming on trusted private networks. Do not
expose port 19999 publicly or reuse this configuration across untrusted networks.

## TrueNAS deployment

Read [TrueNAS guidance](../../truenas/AGENTS.md) first. Back up its configuration
through `playbooks/backup.yml` before the first mutation. Set the existing appdata
path and parent address in ignored `truenas/group_vars/truenas.yml`.
The playbook uses the same ignored streaming key as the Linux agents.

Run from `truenas/`:

```sh
ansible-playbook playbooks/netdata.yml -e @group_vars/truenas.yml --check --diff
ansible-playbook playbooks/netdata.yml -e @group_vars/truenas.yml -e truenas_allow_changes=true
ansible-playbook playbooks/netdata.yml -e @group_vars/truenas.yml -e truenas_allow_changes=true
```

It manages only `homelab-netdata` and its own configuration, cache, and library
directories under existing appdata storage. It does not create datasets or change
pools, networking, SSH, accounts, or the built-in Netdata instance.
Verify both collectors, the pool, and all existing app states after deployment.

## Open WebUI connection

This integration was checked with Open WebUI **0.12.5**. It uses native MCP and
Responses support. No custom chat backend or extra dependency is installed.

Copy `files/netdata/configure_webui.py` into the existing Open WebUI guest.
Run it with that installation's Python environment. Pass a JSON object on stdin:

```json
{
  "openai_api_key": "READ_FROM_PRIVATE_FILE",
  "netdata_url": "http://192.0.2.10:19999/mcp",
  "dashboard_url": "http://192.0.2.10:19999",
  "expected_nodes": ["node-a", "node-b", "backup-node", "nas"]
}
```

Generate this input in memory from the private key file. Do not put the actual
key in a command argument, terminal output, or tracked configuration.
Use `--check` first, apply without it, then check again for an empty change list.
The existing private key file is `proxmox/.maintenance-briefs-openai-key`.
Its retained filename does not imply that the retired bot remains installed.

The helper requires exactly one existing admin. It opens the SQLite database
read-only to identify that account and uses a short-lived local admin token.
It changes configuration through supported application endpoints. It preserves
unrelated providers and tool connections. Before a change, it writes a mode-0600
`before-netdata-<timestamp>.json` settings backup inside the existing data directory.
That backup contains credentials. Never attach or commit it.

The created model is `ask-the-lab`, using `homelab-netdata.gpt-6.1-sol` through
`https://api.openai.com/v1` with `api_type: responses`. GPT-6.1 Sol tool calls use
the Responses API. Encrypted reasoning content is included for stateless follow-ups.
Native tools are attached through `meta.toolIds`. No browser-side API key is needed.
The raw provider model is also admin-only. Select the named custom model to get
the Netdata tools and evidence-focused prompt.

## Verification and recovery

Run `python3 tests/test_netdata.py` with Ansible's Python environment, which
provides Jinja2. Run full `ansible-lint`, syntax checks, check mode, and a live
repeat deployment. These tests cover preservation of unrelated settings,
idempotence, private credentials, tool restrictions, and rendered collection ACLs.

Verify `/api/v2/nodes` on the parent, each source's recent CPU and RAM samples,
and guest/container chart labels. An HTTP 200 alone does not prove live coverage.
Verify MCP discovery and a complete chat that executes tools and returns measured
values. A plain OpenAI-compatible API call without chat metadata can return tool
requests without executing them. Use the actual chat path for acceptance.

For a service problem, stop only the affected new Netdata collector. Existing
Loki/Grafana, backups, updates, and application services are independent.
For chat rollback, restore only the named model/provider/tool entries from the
protected settings backup through Open WebUI. Preserve later unrelated changes.
Removing collector data or the TrueNAS app requires a separate reviewed action.

References: [Netdata MCP](https://learn.netdata.cloud/docs/netdata-ai/mcp),
[Open WebUI MCP](https://docs.openwebui.com/features/extensibility/mcp/),
[Netdata Docker](https://learn.netdata.cloud/docs/netdata-agent/installation/docker),
[OpenAI model](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
