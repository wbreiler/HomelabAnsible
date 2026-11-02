"""Run in NexDeck's venv with its backend on PYTHONPATH."""

import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from app.adapters.base import AdapterError, WidgetData
    from app.adapters.homelab import ADAPTER
except ModuleNotFoundError as error:
    if error.name != "app":
        raise
    raise unittest.SkipTest("Run in NexDeck's venv with its backend on PYTHONPATH.") from error


class HomelabMap(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cluster = WidgetData(meta={"topology": {"places": [
            {"id": "cluster", "name": "Cluster", "parent": None, "status": "ok"},
            {"id": "node/a", "name": "a", "parent": "cluster", "status": "ok"},
            {"id": "a/101", "name": "guest", "parent": "node/a", "status": "ok"},
        ]}})
        self.pve = SimpleNamespace(kind="proxmox", fetch=AsyncMock(return_value=self.cluster))
        self.nas = SimpleNamespace(kind="truenas", fetch=AsyncMock(side_effect=[
            WidgetData(status="bad", metrics={"cpu": 2, "memory": 8}, secondary=[{"label": "Alerts", "value": 3}]),
            WidgetData(items=[{"title": "pool", "subtitle": "ONLINE", "status": "ok"}]),
        ]))
        self.pbs = SimpleNamespace(kind="pbs", fetch=AsyncMock(side_effect=[
            WidgetData(metrics={"cpu": 1}),
            WidgetData(items=[{"title": "backup", "status": "ok"}]),
        ]))
        async def resolve(source):
            return {1: self.pve, 2: self.nas, 3: self.pbs}[source], {}, None
        self.ctx = SimpleNamespace(resolve_integration=AsyncMock(side_effect=resolve))

    async def test_combines_real_hierarchy_without_mutating_sources(self):
        original = deepcopy(self.cluster.meta)
        result = await ADAPTER.fetch("map", {}, {"sources": [1, 2, 3], "show_stopped": False}, self.ctx)
        places = {p["id"]: p for p in result.meta["topology"]["places"]}
        self.assertEqual(places["system/1/node/a"]["parent"], "homelab")
        self.assertEqual(places["system/1/a/101"]["parent"], "system/1/node/a")
        self.assertEqual(places["system/2/storage/0"]["parent"], "system/2")
        self.assertEqual(places["system/3/storage/0"]["parent"], "system/3")
        self.assertIn("3 alerts", places["system/2"]["detail"])
        self.assertEqual(result.status, "bad")
        self.assertEqual(places["system/3"]["status"], "ok")
        self.assertEqual(self.cluster.meta, original)
        self.assertFalse(self.pve.fetch.call_args.args[2]["show_stopped"])

    async def test_unavailable_source_does_not_hide_other_systems(self):
        self.nas.fetch.side_effect = AdapterError("Private failure detail", code="http_error")
        result = await ADAPTER.fetch("map", {}, {"sources": [1, 2, 3]}, self.ctx)
        places = {p["id"]: p for p in result.meta["topology"]["places"]}
        self.assertEqual(places["system/2"]["detail"], "Unavailable")
        self.assertEqual(places["system/2"]["status"], "bad")
        self.assertIn("system/1/a/101", places)
        self.assertIn("system/3/storage/0", places)

    async def test_duplicate_sources_are_collected_once(self):
        result = await ADAPTER.fetch("map", {}, {"sources": [1, 1]}, self.ctx)
        self.ctx.resolve_integration.assert_awaited_once_with(1)
        ids = [p["id"] for p in result.meta["topology"]["places"]]
        self.assertEqual(len(ids), len(set(ids)))

    async def test_invalid_sources_do_not_make_requests(self):
        for sources in ([], "1", [True], [-1], [1, 2, 3, 4]):
            with self.subTest(sources=sources), self.assertRaises(AdapterError):
                await ADAPTER.fetch("map", {}, {"sources": sources}, self.ctx)
        self.ctx.resolve_integration.assert_not_awaited()

    async def test_missing_resolver_is_explicit(self):
        with self.assertRaises(AdapterError):
            await ADAPTER.fetch("map", {}, {"sources": [1]}, SimpleNamespace(resolve_integration=None))


if __name__ == "__main__":
    unittest.main()
