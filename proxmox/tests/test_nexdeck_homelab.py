"""Run in NexDeck's venv with its backend on PYTHONPATH."""

import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

try:
    from app.adapters.base import AdapterError, WidgetData
    from app.adapters.homelab import ADAPTER
    from app.adapters.truenas import _NoCurrentApi
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
        ]), _rpc=AsyncMock(return_value={"app.query": [{"id": "plex", "name": "Plex", "state": "RUNNING"}]}))
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
        self.assertEqual(places["system/2/app/plex"]["parent"], "system/2")
        self.assertEqual(places["system/2/app/plex"]["detail"], "App · Running")
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

    async def test_app_states_and_stopped_filter_exclude_configuration(self):
        self.nas._rpc.return_value = {"app.query": [
            {"id": state.lower(), "state": state, "config": {"secret": "DO_NOT_LEAK"}}
            for state in ("RUNNING", "STOPPED", "DEPLOYING", "CRASHED", "UNKNOWN")
        ]}
        apps, status = await ADAPTER._apps(self.nas, {}, "nas", {})
        self.assertEqual(status, "bad")
        by_id = {app["id"]: app for app in apps}
        self.assertEqual(by_id["nas/app/running"]["status"], "ok")
        self.assertEqual(by_id["nas/app/stopped"]["status"], "unknown")
        self.assertEqual(by_id["nas/app/deploying"]["status"], "warn")
        self.assertEqual(by_id["nas/app/crashed"]["status"], "bad")
        self.assertEqual(by_id["nas/app/unknown"]["status"], "unknown")
        self.assertNotIn("DO_NOT_LEAK", str(apps))
        apps, _ = await ADAPTER._apps(self.nas, {}, "nas", {"show_stopped": False})
        self.assertNotIn("nas/app/stopped", [app["id"] for app in apps])

    async def test_app_query_failure_keeps_host_pool_and_other_systems(self):
        self.nas._rpc.side_effect = _NoCurrentApi(404)
        result = await ADAPTER.fetch("map", {}, {"sources": [1, 2, 3]}, self.ctx)
        places = {p["id"]: p for p in result.meta["topology"]["places"]}
        self.assertEqual(places["system/2/apps"]["detail"], "Unavailable")
        self.assertIn("CPU", places["system/2"]["detail"])
        self.assertIn("system/2/storage/0", places)
        self.assertIn("system/1/a/101", places)
        self.assertIn("system/3/storage/0", places)

    async def test_bad_app_inventory_is_not_treated_as_an_empty_list(self):
        self.nas._rpc.return_value = {"app.query": None}
        apps, status = await ADAPTER._apps(self.nas, {}, "nas", {})
        self.assertEqual(status, "warn")
        self.assertEqual(apps[0]["detail"], "Unavailable")


if __name__ == "__main__":
    unittest.main()
