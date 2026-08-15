#!/usr/bin/env python3
"""Reconcile Uptime Kuma's admin user, notification providers, groups, and
monitors against a desired-state JSON file. Additive only: anything present
in Kuma but not listed in the desired state is left alone.

Depends on the third-party uptime_kuma_api client, not an official Kuma API.
"""
import argparse
import json
import sys

from uptime_kuma_api import UptimeKumaApi


def find_by_name(items, name):
    for item in items:
        if item.get("name") == name:
            return item
    return None


def ensure_admin(api, username, password, changed):
    try:
        api.login(username, password)
    except Exception:
        api.setup(username, password)
        changed.append("admin user created")


def ensure_notifications(api, notifications_desired, changed):
    """Returns {notification name: id} for every desired notification."""
    ids = {}
    existing_list = api.get_notifications()
    for notif in notifications_desired:
        config = notif.get("config", {})
        existing = find_by_name(existing_list, notif["name"])
        if existing is None:
            result = api.add_notification(
                name=notif["name"],
                type=notif["type"],
                isDefault=notif.get("isDefault", False),
                **config,
            )
            ids[notif["name"]] = result["id"]
            changed.append("notification {} created".format(notif["name"]))
            existing_list = api.get_notifications()
        else:
            ids[notif["name"]] = existing["id"]
            if any(existing.get(key) != value for key, value in config.items()):
                api.edit_notification(
                    existing["id"],
                    name=notif["name"],
                    type=notif["type"],
                    isDefault=notif.get("isDefault", False),
                    **config,
                )
                changed.append("notification {} updated".format(notif["name"]))
    return ids


def ensure_groups(api, groups, monitors, changed):
    group_ids = {}
    for group in groups:
        existing = find_by_name(monitors, group["name"])
        if existing is None:
            result = api.add_monitor(type="group", name=group["name"])
            group_ids[group["name"]] = result["monitorID"]
            changed.append("group {} created".format(group["name"]))
            monitors = api.get_monitors()
        else:
            group_ids[group["name"]] = existing["id"]
    return group_ids, monitors


def ensure_monitors(api, monitors_desired, monitors, group_ids, notification_ids, changed):
    for mon in monitors_desired:
        payload = {k: v for k, v in mon.items() if k not in ("group", "notify", "critical")}
        if mon.get("group"):
            payload["parent"] = group_ids.get(mon["group"])
        notify = mon.get("notify", False)
        payload["notificationIDList"] = (
            {str(notification_ids[notify]): True} if notify and notify in notification_ids else {}
        )

        existing = find_by_name(monitors, mon["name"])
        if existing is None:
            api.add_monitor(**payload)
            changed.append("monitor {} created".format(mon["name"]))
            monitors = api.get_monitors()
        elif any(existing.get(k) != v for k, v in payload.items() if k in existing):
            api.edit_monitor(existing["id"], **payload)
            changed.append("monitor {} updated".format(mon["name"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()

    with open(args.state, encoding="utf-8") as f:
        desired = json.load(f)

    changed = []
    api = UptimeKumaApi(args.url)
    try:
        ensure_admin(api, desired["admin_username"], desired["admin_password"], changed)
        notification_ids = ensure_notifications(api, desired.get("notifications", []), changed)
        monitors = api.get_monitors()
        group_ids, monitors = ensure_groups(api, desired.get("groups", []), monitors, changed)
        ensure_monitors(
            api, desired.get("monitors", []), monitors, group_ids, notification_ids, changed
        )
    finally:
        api.disconnect()

    print(json.dumps({"changed": bool(changed), "details": changed}))


if __name__ == "__main__":
    main()
