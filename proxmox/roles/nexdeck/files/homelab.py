"""Combine the existing Proxmox, TrueNAS and PBS adapters in one native map."""

import asyncio
from urllib.parse import urlsplit

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType
from .core import parse_links
from .truenas import _NoCurrentApi


LABELS = {"proxmox": "Proxmox", "truenas": "TrueNAS", "pbs": "PBS"}
SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "bad": 3}


def app_links(value: str) -> dict[str, str]:
    links = {}
    for item in parse_links(value if isinstance(value, str) else ""):
        try:
            url = urlsplit(item["url"])
            if (url.scheme in ("http", "https") and url.hostname
                    and url.username is None and url.password is None
                    and not any(char.isspace() for char in item["url"])):
                links[item["title"]] = item["url"]
        except ValueError:
            continue
    return links


class HomelabAdapter(Adapter):
    kind = "homelab"
    label = "Homelab"
    category = "hosts"
    description = "Compute, storage and backup in one live map."
    icon = "lucide:network"
    beta = False
    needs_integration = False
    widgets = (
        WidgetType(
            kind="map",
            label="Homelab map",
            description="Proxmox hosts and guests, TrueNAS apps and pools, and PBS datastores.",
            renderer="topology",
            default_size=(12, 6),
            refresh_seconds=30,
            options=(
                Field("sources", "Systems", type="integrations", default=[],
                      options=tuple(LABELS.items()),
                      help="Select the Proxmox, TrueNAS and PBS connections."),
                Field("show_stopped", "Show stopped guests and apps", type="bool", default=True),
                Field("app_links", "Dashboard links", type="textarea", default="",
                      help="One key | http(s) URL per line. Use host/name, guest/VMID, or a TrueNAS app ID. Opens in a new tab.",
                      placeholder="plex | https://plex.example.com/web/index.html"),
            ),
        ),
    )

    async def fetch(self, widget_kind: str, config: dict, options: dict, ctx: Context) -> WidgetData:
        sources = options.get("sources") or []
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 3
                or any(type(source) is not int or source <= 0 for source in sources)):
            raise AdapterError("Select up to three systems in the map settings.", code="bad_sources")
        if ctx.resolve_integration is None:
            raise AdapterError("System connections cannot be resolved here.", code="no_resolver")
        branches = await asyncio.gather(*(
            self._branch(source, options, ctx) for source in dict.fromkeys(sources)
        ))
        status = max((state for _places, state in branches), key=lambda state: SEVERITY.get(state, 1))
        places = [{"id": "homelab", "name": "Homelab", "parent": None,
                   "kind": "cluster", "status": status, "detail": "Compute · storage · backup"}]
        for branch, _state in branches:
            places.extend(branch)
        links = app_links(options.get("app_links", ""))
        for place in places:
            if place.get("kind") == "host":
                key = f"host/{place['name'].lower()}"
            elif "/lxc/" in place["id"] or "/qemu/" in place["id"]:
                # VMIDs stay stable when Proxmox moves a guest between hosts.
                key = f"guest/{place['id'].rsplit('/', 1)[1]}"
            else:
                continue
            if url := links.get(key):
                place["url"] = url
        return WidgetData(status=status, meta={"topology": {"places": places}})

    async def _branch(self, source: int, options: dict, ctx: Context) -> tuple[list[dict], str]:
        root = f"system/{source}"
        label = f"Connection {source}"
        try:
            adapter, config, source_ctx = await ctx.resolve_integration(source)
            if adapter.kind not in LABELS:
                raise AdapterError("Unsupported system type.", code="bad_source")
            label = LABELS[adapter.kind]
            if adapter.kind == "proxmox":
                data = await adapter.fetch("map", config, options, source_ctx)
                if data.error or not data.meta.get("topology", {}).get("places"):
                    raise AdapterError("The cluster map is unavailable.", code="source_unavailable")
                original = data.meta["topology"]["places"]
                roots = {place["id"] for place in original if place.get("parent") is None}
                # Keep physical hosts as peers of TrueNAS and PBS, under Homelab.
                places = [{**place, "id": f"{root}/{place['id']}",
                           "parent": "homelab" if place.get("parent") in roots
                           else f"{root}/{place['parent']}"}
                          for place in original if place["id"] not in roots]
                return places, data.status
            system, storage = await asyncio.gather(
                adapter.fetch("system", config, {}, source_ctx),
                adapter.fetch("pools" if adapter.kind == "truenas" else "datastores", config, {}, source_ctx),
            )
            if system.error or storage.error:
                raise AdapterError("The system is unavailable.", code="source_unavailable")
            status = max((system.status, storage.status), key=lambda state: SEVERITY.get(state, 1))
            details = [f"{name} {system.metrics[key]:g}%" for key, name in (("cpu", "CPU"), ("memory", "RAM"))
                       if system.metrics.get(key) is not None]
            details.extend(f"{item['value']} alerts" for item in system.secondary
                           if item.get("label") == "Alerts" and item.get("value"))
            places = [{"id": root, "name": label, "kind": "host", "parent": "homelab",
                       "status": status, "detail": " · ".join(details)}]
            for index, item in enumerate(storage.items):
                places.append({"id": f"{root}/storage/{index}", "name": str(item.get("title") or "Storage"),
                               "kind": "storage", "parent": root, "status": item.get("status") or "unknown",
                               "detail": str(item.get("subtitle") or item.get("value") or "")})
            if adapter.kind == "truenas":
                apps, app_status = await self._apps(adapter, config, root, options)
                places.extend(apps)
                status = max((status, app_status), key=lambda state: SEVERITY.get(state, 1))
                places[0]["status"] = status
            return places, status
        except (AdapterError, TimeoutError):
            return [{"id": root, "name": label, "kind": "host", "parent": "homelab",
                     "status": "bad", "detail": "Unavailable"}], "bad"

    async def _apps(self, adapter: Adapter, config: dict, root: str, options: dict) -> tuple[list[dict], str]:
        try:
            # App discovery uses the current WebSocket API without a legacy REST fallback.
            apps = (await adapter._rpc(config, ["app.query"]))["app.query"]
            if not isinstance(apps, list) or any(not isinstance(app, dict) or not app.get("id") for app in apps):
                raise AdapterError("App inventory is unavailable.", code="bad_apps")
        except (AdapterError, TimeoutError, _NoCurrentApi):
            return [{"id": f"{root}/apps", "name": "Apps", "kind": "container", "parent": root,
                     "status": "warn", "detail": "Unavailable"}], "warn"
        places = []
        status = "ok"
        links = app_links(options.get("app_links", ""))
        for app in sorted(apps, key=lambda item: str(item.get("name") or item["id"]).lower()):
            state = str(app.get("state") or "UNKNOWN").upper()
            if state == "STOPPED" and not options.get("show_stopped", True):
                continue
            health = {"RUNNING": "ok", "STOPPED": "unknown", "DEPLOYING": "warn", "CRASHED": "bad"}.get(state, "unknown")
            if health in ("warn", "bad"):
                status = max((status, health), key=SEVERITY.get)
            node = {"id": f"{root}/app/{app['id']}", "name": str(app.get("name") or app["id"]),
                    "kind": "container", "parent": root, "status": health,
                    "detail": f"App · {state.replace('_', ' ').title()}"}
            if url := links.get(str(app["id"])):
                node["url"] = url
            places.append(node)
        return places, status


ADAPTER = HomelabAdapter()
