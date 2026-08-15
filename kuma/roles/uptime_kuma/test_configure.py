#!/usr/bin/env python3
"""Self-check for files/configure.py. Run directly: python3 test_configure.py
Stubs the uptime_kuma_api dependency so this needs no live Kuma or network.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.modules["uptime_kuma_api"] = types.SimpleNamespace(UptimeKumaApi=mock.MagicMock())
sys.path.insert(0, str(Path(__file__).parent / "files"))
import configure  # noqa: E402


class FindByNameTests(unittest.TestCase):
    def test_finds_matching_item(self):
        items = [{"name": "a", "id": 1}, {"name": "b", "id": 2}]
        self.assertEqual(configure.find_by_name(items, "b"), {"name": "b", "id": 2})

    def test_returns_none_when_missing(self):
        self.assertIsNone(configure.find_by_name([{"name": "a"}], "missing"))


class EnsureMonitorsTests(unittest.TestCase):
    def test_creates_missing_monitor_and_reports_change(self):
        api = mock.MagicMock()
        api.add_monitor.return_value = {"monitorID": 1}
        api.get_monitors.return_value = []
        changed = []

        configure.ensure_monitors(
            api,
            [{"name": "svc", "type": "http", "url": "http://x"}],
            [],
            {},
            notification_ids={},
            changed=changed,
        )

        api.add_monitor.assert_called_once_with(
            name="svc", type="http", url="http://x", notificationIDList={}
        )
        self.assertEqual(changed, ["monitor svc created"])

    def test_skips_unchanged_monitor(self):
        api = mock.MagicMock()
        existing = [{"id": 5, "name": "svc", "type": "http", "url": "http://x"}]
        changed = []

        configure.ensure_monitors(
            api,
            [{"name": "svc", "type": "http", "url": "http://x"}],
            existing,
            {},
            notification_ids={},
            changed=changed,
        )

        api.edit_monitor.assert_not_called()
        self.assertEqual(changed, [])

    def test_critical_field_is_stripped_from_the_kuma_payload(self):
        # `critical` picks the notification tier in the role's tasks (see
        # tasks/main.yml's resolve steps); Kuma itself has no such field.
        api = mock.MagicMock()
        api.add_monitor.return_value = {"monitorID": 1}
        api.get_monitors.return_value = []
        changed = []

        configure.ensure_monitors(
            api,
            [{"name": "svc", "type": "http", "url": "http://x", "notify": "Discord", "critical": False}],
            [],
            {},
            notification_ids={"Discord": 42},
            changed=changed,
        )

        api.add_monitor.assert_called_once_with(
            name="svc", type="http", url="http://x", notificationIDList={"42": True}
        )

    def test_silent_shared_monitor_gets_no_notification(self):
        api = mock.MagicMock()
        api.add_monitor.return_value = {"monitorID": 1}
        api.get_monitors.return_value = []
        changed = []

        configure.ensure_monitors(
            api,
            [{"name": "svc", "type": "http", "url": "http://x", "notify": False}],
            [],
            {},
            notification_ids={"Discord": 42},
            changed=changed,
        )

        api.add_monitor.assert_called_once_with(
            name="svc", type="http", url="http://x", notificationIDList={}
        )

    def test_monitor_notifies_the_named_provider(self):
        api = mock.MagicMock()
        api.add_monitor.return_value = {"monitorID": 1}
        api.get_monitors.return_value = []
        changed = []

        configure.ensure_monitors(
            api,
            [{"name": "svc", "type": "http", "url": "http://x", "notify": "Quorum Relay"}],
            [],
            {},
            notification_ids={"Discord": 42, "Quorum Relay": 7},
            changed=changed,
        )

        api.add_monitor.assert_called_once_with(
            name="svc", type="http", url="http://x", notificationIDList={"7": True}
        )


class EnsureNotificationsTests(unittest.TestCase):
    def test_creates_missing_notification(self):
        api = mock.MagicMock()
        api.get_notifications.return_value = []
        api.add_notification.return_value = {"id": 42}
        changed = []

        ids = configure.ensure_notifications(
            api,
            [{"name": "Discord", "type": "discord", "config": {"a": 1}, "isDefault": True}],
            changed,
        )

        api.add_notification.assert_called_once_with(
            name="Discord", type="discord", a=1, isDefault=True
        )
        self.assertEqual(ids, {"Discord": 42})
        self.assertEqual(changed, ["notification Discord created"])

    def test_reuses_existing_notification_id(self):
        api = mock.MagicMock()
        api.get_notifications.return_value = [
            {"id": 9, "name": "Discord", "type": "discord", "a": 1}
        ]
        changed = []

        ids = configure.ensure_notifications(
            api,
            [{"name": "Discord", "type": "discord", "config": {"a": 1}, "isDefault": True}],
            changed,
        )

        api.add_notification.assert_not_called()
        api.edit_notification.assert_not_called()
        self.assertEqual(ids, {"Discord": 9})
        self.assertEqual(changed, [])

    def test_updates_changed_notification_with_flat_provider_options(self):
        api = mock.MagicMock()
        api.get_notifications.return_value = [
            {"id": 9, "name": "Discord", "type": "discord", "a": 1}
        ]
        changed = []

        ids = configure.ensure_notifications(
            api,
            [{"name": "Discord", "type": "discord", "config": {"a": 2}, "isDefault": True}],
            changed,
        )

        api.edit_notification.assert_called_once_with(
            9, name="Discord", type="discord", a=2, isDefault=True
        )
        self.assertEqual(ids, {"Discord": 9})
        self.assertEqual(changed, ["notification Discord updated"])


if __name__ == "__main__":
    unittest.main()
