# Approved app repairs in Ask the lab

Use **Ask the lab · GPT-6.1 Sol** in the existing Open WebUI.
Ask it to investigate an issue and propose a supported repair. The chat shows
an exact plan. Its confirmation dialog is the execution gate.

1. Ask for an investigation or a repair.
2. Review the app, exact old/new values, backup, and service impact.
3. Select Confirm or Cancel in the browser dialog.
4. Read the verification result and remaining health findings in the same chat.

A chat message such as “approved” does not authorize execution. The model cannot
supply approval. Approval requires the configured owner's authenticated browser.
An unanswered dialog expires after three minutes. Plans expire after ten minutes.
Only one proposal may await approval or execute at a time.

## Available repairs

| Application | Configuration changes | Recovery action |
| --- | --- | --- |
| Sonarr, Radarr, Lidarr | Allowed hosts, existing download-client connection fields, existing remote-path mappings | Restart the application |
| Prowlarr | Allowed hosts, existing download-client connection fields | Restart the application |
| Seerr | Plex connection settings | Verified library catalog sync and replacement selection |
| SABnzbd | None | Resume a paused queue |
| repair-drill | Toggle an isolated fixture between `before` and `after` | No service changes |

The live catalog determines which instances and records are configured.
Download destinations must match an exact configured host/port/TLS/base-path
combination. Mapping paths stay within configured media roots. Allowed hosts
must retain the verified direct and reverse-proxy names. Existing records can
be edited. Record creation and deletion are unavailable except through Seerr's
explicit catalog refresh described below.

Seerr 3.5.0 marks `libraries` read-only on its Plex settings endpoint.
A `sync_libraries` proposal instead uses two supported operations:

1. POST `/api/v1/settings/plex/library/sync` without a body to refresh the complete catalog.
2. PUT `/api/v1/settings/plex/library/{id}` with `{"enabled": true}` if the replacement was previously enabled.

The proposal shows the expected complete catalog and both steps. Exactly one
verified old/new ID pair must match the current configuration. Names and types
must match fresh Plex evidence. Existing IDs retain their enabled flags and
scan timestamps. A replacement ID starts disabled and loses its old scan marker.
The second request restores its approved selection. No full scan or restart runs.
Background `lastScan` timestamps may advance during review. Only those timestamps
are excluded from the stale-state comparison. Other configuration drift blocks execution.

The private policy's `library_id_repairs` list stores `{name, type, from_id, to_id}`
records. `library_catalog` stores the complete expected `{id, name, type}` list.
`library_id_repairs_verified_at` is their verification time in Unix seconds.
Read Plex's library sections and verify the server identity before enabling a
pair. Match Seerr's filter: only movie/show libraries with a metadata agent.
Evidence expires after one hour and is checked again before execution.
The repair tool receives no Plex credential.

Sync refreshes the entire catalog. A catalog change on Plex after the read-only
check can therefore affect Seerr. If the sync response differs from the expected
catalog, the tool stops before the enable request. A partial failure can leave
the replacement disabled. There is no automatic retry or library rollback.
Inspect the saved step receipts and current configuration before a new proposal.

This version cannot repair every observed issue. It cannot replace credentials,
change indexer accounts, modify arbitrary files, manage Docker, install updates,
change guest power, or alter host, network, storage, or backup configuration.
It must explain unsupported repairs instead of claiming it can execute them.
Do not resolve warnings by disabling checks or suppressing their reports.

Seerr's Plex endpoint also detects the server name and ID. Its implementation
can alter in-memory settings before a failed connection test returns an error.
The proposal names this risk. A failed response is not proof that nothing changed.

## Approval and privilege boundary

`files/app-repairs/tool.py` is a native Open WebUI Python tool. It uses the
platform's `confirmation` event and status events. It does not expose another
HTTP service, shell, SSH credential, Docker socket, or generic API-request tool.
The native platform binds the event reply to the requesting user's session.
The repair code accepts only the literal boolean `True` as confirmation.
This guard works independently of WebUI's optional global tool-permissions mode.

App API credentials remain administrative credentials. The code restricts their
use to fixed routes and editable fields. The model receives only selected
configuration fields, proposals, and results. It never receives keys or complete
configuration objects. Redirects and environment proxies are disabled. App
requests use fixed private IP endpoints over the existing trusted LAN.

The private tool has no access grants. Code also checks the exact owner ID and
admin role on every method. It binds plans to that owner and chat, and rejects
scheduled/internal requests. Model arguments cannot set the injected identity
or approval callback. Protect the WebUI administrator account and its plugin
code: an administrator can modify this enforcement code.

## Backups, attempts, and verification

A proposal stores the original API resource privately. Immediately before a
write, the executor checks the current resource and private policy against the
saved plan. Stale plans require new approval. It saves and flushes a separate
backup before marking an attempt as started. Most actions send one mutation.
A Seerr library repair sends the two fixed requests described above, at most once each.

Backups and plan records live under `/root/.open-webui/repair-plans/` with
mode `0700` on the directory and `0600` on JSON files. They can contain complete
API resources and secrets. Never attach them to a chat or commit them.
For a restart/resume, the backup is a precheck receipt. It is not a disk or
application-data backup because those actions do not edit configuration.

Reads can retry during verification. Writes never retry automatically.
An ambiguous response or interrupted process requires investigation. The saved
`attempting` status means the result may be unknown. Canceling generation after
approval does not undo an already authorized attempt. The tool waits for its
worker to finish before releasing the execution lock.

A verified setting means the API returned the requested value. It does not
prove the original issue is fixed. The model must inspect fresh observer health
and logs afterward. Restart verification requires a changed app start time.
Resume verification requires an unpaused queue.

Ask for a rollback of the repair ID to create a new configuration proposal.
Rollback also requires approval. Library sync has no supported rollback action.
For editable fields, rollback reverses only the fields from the original
attempt. It does not undo downloads, imports, or other jobs triggered meanwhile.
Seerr's detected name/ID are derived again by its API. There is no automatic
rollback. The protected backup supports investigation and separately reviewed recovery.

The app APIs do not provide an atomic compare-and-swap for these settings.
Avoid simultaneous edits in the app while approving a repair. The local lock
serializes this tool's attempts, not changes made by another administrator.

## Deployment

Use the existing `files/netdata/configure_webui.py` setup helper inside the
WebUI guest. The helper preserves unrelated providers and tools and writes a
mode-`0600` backup before updating its own model/tool/configuration.

Prepare ignored `.app-repairs.json` from
`files/app-repairs/config.json.example`, mode `0600`. Copy only required existing
app keys through protected input. Discover current connection fields through
read-only API requests. Verify reverse-proxy names and destinations before
allowlisting them. Do not enable arbitrary addresses or broad filesystem roots.

Add this object to the existing helper's JSON stdin settings:

```python
settings['repairs'] = {
    'config': json.loads(Path('.app-repairs.json').read_text()),
    'source': Path('files/app-repairs/tool.py').read_text(),
}
```

The helper installs the private policy at
`/root/.config/homelab-repairs.json`, registers the `homelab_repairs` native tool,
and attaches it to `ask-the-lab`. The sole existing administrator must match the
configured owner. No service restart is required. Run `--check`, apply, then
repeat `--check` and require an empty changes list. Include `repairs` in future
setup runs to retain the model attachment. Omitting it removes that attachment.
The existing app observers remain read-only.

The OpenAI key remains the existing private WebUI connection. Model and API
settings remain GPT-6.1 Sol, Responses, and `store: false`. No additional OpenAI
key, subscription, scheduled worker, or dependency is required.

## Validation

Run from `proxmox/`:

```sh
python3 -m unittest discover -s tests -p test_app_repairs.py
python3 -m unittest discover -s tests -p test_netdata.py
ansible-lint
ansible-playbook site.yml --syntax-check
```

In the installed Python environment, validate the actual tool schemas and
ensure injected `__...__` arguments are absent from model-visible properties.
Test a real chat without a browser session and confirm execution is refused.

Use **Test repair approval** or ask:

> Run the safe repair approval drill using only repair-drill. Show me the confirmation dialog.

First cancel a drill. Then request another drill and confirm it. Check that only
the fixture changed, that its backup contains the previous value, and that a
second invocation of the same plan is refused. Do not use a real application
repair as an installation test. Actual repairs need their own concrete approval.

Platform references: [Open WebUI events](https://docs.openwebui.com/features/extensibility/plugin/development/events/)
and [official OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
