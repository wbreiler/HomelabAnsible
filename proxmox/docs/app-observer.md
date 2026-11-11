# Application health and filtered logs

[Approved app repairs](app-repairs.md) use a separate native WebUI tool.
The observation endpoints described here remain read-only.

**Ask the lab** combines Netdata metrics with fixed read-only application
observations. Use the same Open WebUI model. Ask, for example:

- Are the apps healthy, including their own health checks and recent errors?
- Why does Sonarr report a warning?
- Does Forgejo have failed mirror jobs despite passing its database check?
- Is Plex healthy, and what remains unverified?

The Linux observer runs beside Loki as a systemd dynamic user. The TrueNAS
observer is a separate custom app. Both use the same standard-library Python
implementation in `files/app-observer/server.py`. Neither has an OpenAI key.
Open WebUI authenticates to each observer and sends selected results to OpenAI.

## Evidence and limits

| Adapter | Returned evidence |
| --- | --- |
| `arr` | Version, health warnings, aggregate queue counts/errors. Use `queue: false` for Prowlarr. |
| `sabnzbd` | Queue status, pause state, counts, speed, remaining size, and free space. No media names. |
| `forgejo` | Built-in status and reported cache/database check results. |
| `json_health` | Built-in JSON status. `healthy_status` defaults to `healthy`. |
| `http` | Response status only. This yields `responsive`, not `healthy`. |
| `docker` | Exact configured container states, healthcheck status, restart count, and OOM/exit evidence. |
| `unknown` | Explicit missing coverage. Resource metrics remain available through Netdata. |

Health responses include up to three filtered diagnostic excerpts from each
app's configured log sources. This preserves job errors even when an app's
basic self-check passes. The model must distinguish a passing dependency check
from successful mirroring, imports, downloads, playback, or player login.

The Docker adapter does not add or modify healthchecks. A running container with
no healthcheck remains `running_unverified`. An intentionally stopped app does
not automatically become an outage. Unexpected activity becomes `needs_review`.
A missing endpoint, authentication failure, or invalid response remains unknown.

At the 2026-11-10 deployment, the private registry contained 27 Linux app entries
and 12 TrueNAS app entries. These counts describe a snapshot, not automatic
coverage of every future guest. Some entries intentionally report missing checks.
Minecraft, LANCache internals, and several utility guests still need dedicated
functional checks. No agent or command executor was installed in those guests.

## Read and privacy boundaries

The AI gets three operations per observer: `list_apps`, `get_app_health`, and
`get_app_logs`. `get_app_health(app="all")` performs a bounded parallel overview.
There is no command, URL, file-path, raw LogQL, or Docker-operation parameter.
The service accepts only its fixed GET routes. It rejects write methods,
unknown parameters, duplicate parameters, and unconfigured app names.

The Linux service reads only configured Loki source selectors through the
existing loopback listener. Public Loki query access remains blocked. App API
requests use fixed private-IP endpoints and reject redirects. Application keys
remain in mode-0600 configuration and systemd credentials. Some app keys have
write privileges upstream, but this service exposes only fixed read queries.
Do not provide those keys directly to the model or attach generic API tools.

Each observer requires a separate bearer token and exact source-IP allowlist.
Listeners bind to selected private addresses. This deployment uses HTTP within
the trusted homelab network. Do not expose these ports publicly or carry their
credentials over untrusted networks without authenticated TLS.

The user explicitly approved the TrueNAS collector's Docker socket access.
Its non-root container has no Linux capabilities, a read-only filesystem, and
only its code, private configuration, and Docker socket mounted. It reads fixed
container inspect and log endpoints. **The socket itself still permits Docker
administration. A read-only bind mount does not restrict Docker API methods.**
Do not add this collector to another host without reviewing that boundary.
No host PID namespace, host root filesystem, SSH key, or shell tool is required.

Log reads default to 15 minutes and 30 excerpts. Limits are 60 minutes and
50 excerpts, with at most 200 upstream lines per configured source/container.
Responses over 1 MiB are rejected. Only diagnostic lines are eligible.
Known keys and common secret patterns are removed or cause a line to be withheld.
URLs, paths, emails, and long opaque values are also filtered before tool output.
Sensitive authentication apps and Open WebUI do not have log sources configured
in the initial registry. There is no chat, vault, library, or document-content API.

Redaction reduces exposure. It cannot prove that arbitrary logs contain no
personal data or unknown secret formats. Review new sources and add regression
fixtures before extending the allowlist. The model treats excerpts as untrusted
text and does not follow instructions, links, or commands contained in them.

Loki timestamps can be ingestion times. Recollected files can contain older
messages. Results label these as `loki_ingestion` and preserve a detected
`source_time_text` without inventing its timezone. Docker timestamps are labeled
`docker_event`. Empty results do not establish health, completeness, or fresh log
delivery. Debug-level messages containing an error-related word can also appear.

## Deployment

Read each project's `AGENTS.md`. Preserve SSH control sockets. No guest lifecycle
or existing application configuration is managed by these playbooks.

Copy the relevant tracked `files/app-observer/config.json.example` to the
project's ignored `.app-observer.json`, mode 0600. Replace all placeholders.
Inspect actual endpoint versions, ports, container names, and existing Loki
labels. Retrieve needed app keys through protected input, never terminal output.
Generate two independent tokens with `secrets.token_urlsafe(48)` in the protected
configuration-writing process. Never print them or place them in arguments.

From `proxmox/`, reuse the Netdata parent inventory:

```sh
ansible-playbook -i inventory.yml -i .netdata-inventory.yml app-observer.yml -e @.app-observer.json --check --diff
ansible-playbook -i inventory.yml -i .netdata-inventory.yml app-observer.yml -e @.app-observer.json
```

For TrueNAS, first export a protected configuration backup with
`playbooks/backup.yml`. Review Docker socket authorization. From `truenas/`:

```sh
ansible-playbook playbooks/app-observer.yml -e @.app-observer.json --check --diff
ansible-playbook playbooks/app-observer.yml -e @.app-observer.json -e truenas_allow_changes=true
```

This manages only `homelab-app-observer` and its own directory under existing
appdata storage. It does not modify other apps, datasets, pools, networking,
SSH, or host accounts. The official Python image is pinned by digest.
Repeat both playbooks and require `changed=0`.

Add `observers` to the protected stdin settings passed to
[`configure_webui.py`](../files/netdata/configure_webui.py):

```json
{
  "observers": [
    {"id": "homelab-apps", "name": "Linux application health", "url": "http://192.0.2.10:19998", "token": "READ_FROM_PRIVATE_CONFIG"},
    {"id": "nas-apps", "name": "TrueNAS application health", "url": "http://192.0.2.14:19998", "token": "READ_FROM_PRIVATE_CONFIG"}
  ]
}
```

Merge these with the existing Netdata/OpenAI settings described in
[the Netdata guide](netdata.md). Run `--check`, apply, then check again.
The helper preserves unrelated providers and tool connections and keeps a
protected settings backup. The existing private model gains both tool IDs.
No OpenAI provider credential is copied to the observer services.

## Verification

Run `tests/test_app_observer.py` and `tests/test_netdata.py` with Ansible's Python.
The HTTP boundary test needs permission to bind a temporary loopback port.
Fixtures verify authentication, forbidden methods/routes, query bounds,
redirect rejection, credential filtering, Docker framing, partial health,
old event timestamps, and preservation of unrelated WebUI settings.

Run full Ansible lint and syntax checks in both projects. Verify live app
responses, denied unauthenticated requests, unchanged app states, storage health,
and idempotent deployment. Finish with an actual Open WebUI tool conversation.
A schema-fetch success does not prove the model executed a tool.

To disable observation, remove these two tool attachments from the private
model and stop only the observer services. Do not remove app data, alter app
keys, or stop workloads as part of observation troubleshooting.
