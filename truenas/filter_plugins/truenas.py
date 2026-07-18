"""Filters used by the TrueNAS desired-state roles."""


def _is_subset(desired, current):
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        return all(
            key in current and _is_subset(value, current[key])
            for key, value in desired.items()
        )

    if isinstance(desired, list):
        return isinstance(current, list) and desired == current

    return desired == current


def truenas_is_subset(desired, current):
    """Return whether desired recursively matches the corresponding current keys."""
    return _is_subset(desired, current)


def truenas_find_match(items, match):
    """Return the first object containing all match keys, or an empty object."""
    return next((item for item in items if _is_subset(match, item)), {})


def truenas_dataset_properties(dataset):
    """Flatten TrueNAS dataset property objects to their effective values."""
    result = {}
    for key, value in dataset.items():
        if isinstance(value, dict) and "value" in value:
            result[key] = value["value"]
        else:
            result[key] = value
    return result


def truenas_normalize_user(user, groups):
    """Replace TrueNAS group IDs/objects with stable group names."""
    group_by_id = {group["id"]: group["name"] for group in groups}
    result = dict(user)
    primary = user.get("group")
    if isinstance(primary, dict):
        result["group"] = primary.get("bsdgrp_group")
    result["groups"] = [
        group_by_id[group_id]
        for group_id in user.get("groups", [])
        if group_id in group_by_id
    ]
    return result


class FilterModule:
    def filters(self):
        return {
            "truenas_is_subset": truenas_is_subset,
            "truenas_find_match": truenas_find_match,
            "truenas_dataset_properties": truenas_dataset_properties,
            "truenas_normalize_user": truenas_normalize_user,
        }
