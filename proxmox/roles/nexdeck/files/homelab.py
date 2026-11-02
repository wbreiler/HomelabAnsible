"""Combine the existing Proxmox, TrueNAS and PBS adapters in one native map."""

import asyncio

from .base import Adapter, AdapterError, Context, Field, WidgetData, WidgetType


LABELS = {"proxmox": "Proxmox", "truenas": "TrueNAS", "pbs": "PBS"}
SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "bad": 3}


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
            description="Proxmox hosts and guests, TrueNAS pools, and PBS datastores.",
            renderer="topology",
            default_size=(12, 6),
            refresh_seconds=30,
            options=(
                Field("sources", "Systems", type="integrations", default=[],
                      options=tuple(LABELS.items()),
                      help="Select the Proxmox, TrueNAS and PBS connections."),
                Field("show_stopped", "Show stopped guests", type="bool", default=True),
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
            return places, status
        except (AdapterError, TimeoutError):
            return [{"id": root, "name": label, "kind": "host", "parent": "homelab",
                     "status": "bad", "detail": "Unavailable"}], "bad"


ADAPTER = HomelabAdapter()
