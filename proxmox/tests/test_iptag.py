#!/usr/bin/env python3
"""Unit tests for the repository-owned IP-Tag runtime."""

from __future__ import annotations

import importlib.util
import ipaddress
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).parents[1] / "roles/iptag/files/iptag.py"
SPEC = importlib.util.spec_from_file_location("iptag_runtime", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
IPTAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = IPTAG
SPEC.loader.exec_module(IPTAG)


class IPTagRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = IPTAG.Settings(
            networks=(ipaddress.ip_network("10.0.0.0/8"),),
            tag_format="last_octet",
            loop_interval=300,
            debug=False,
            command_timeout=8,
        )

    def test_read_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "iptag.conf"
            config.write_text(
                "\n".join(
                    [
                        "CIDR_LIST=10.0.0.0/8,192.168.0.0/16",
                        "TAG_FORMAT=last_two_octets",
                        "LOOP_INTERVAL=600",
                        "DEBUG=true",
                        "COMMAND_TIMEOUT=5",
                    ]
                ),
                encoding="utf-8",
            )
            settings = IPTAG.read_config(config)

        self.assertEqual(settings.tag_format, "last_two_octets")
        self.assertEqual(settings.loop_interval, 600)
        self.assertTrue(settings.debug)
        self.assertEqual(settings.command_timeout, 5)
        self.assertIn(ipaddress.ip_network("192.168.0.0/16"), settings.networks)

    def test_invalid_cidr_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "iptag.conf"
            config.write_text(
                "CIDR_LIST=not-a-network\nTAG_FORMAT=full\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid CIDR"):
                IPTAG.read_config(config)

    def test_parse_guest_lists(self) -> None:
        pct_output = """VMID Status Lock Name
100 running      forgejo
101 stopped      prowlarr
"""
        qm_output = """VMID NAME       STATUS     MEM(MB)
200  build-vm   running    4096
"""
        self.assertEqual(
            IPTAG.parse_guest_list(pct_output),
            {"100": "running", "101": "stopped"},
        )
        self.assertEqual(IPTAG.parse_guest_list(qm_output), {"200": "running"})

    def test_static_lxc_addresses(self) -> None:
        config = """
net0: name=eth0,bridge=vmbr0,hwaddr=AA:BB:CC:DD:EE:FF,ip=10.10.30.42/24
net1: name=eth1,bridge=vmbr1,ip=dhcp
"""
        self.assertEqual(
            IPTAG.parse_static_lxc_addresses(config),
            [ipaddress.ip_address("10.10.30.42")],
        )

    def test_desired_tags_replace_only_numeric_ip_tags(self) -> None:
        tags = IPTAG.desired_tags(
            ["2", "monitoring", "30.9"],
            [
                ipaddress.ip_address("10.10.30.42"),
                ipaddress.ip_address("172.16.0.8"),
            ],
            self.settings,
        )
        self.assertEqual(tags, ["42", "monitoring"])

    def test_full_tag_format(self) -> None:
        settings = IPTAG.Settings(
            networks=(ipaddress.ip_network("10.0.0.0/8"),),
            tag_format="full",
            loop_interval=300,
            debug=False,
            command_timeout=8,
        )
        self.assertEqual(
            IPTAG.format_address(ipaddress.ip_address("10.10.30.42"), settings),
            "10.10.30.42",
        )

    def test_reconcile_running_lxc_updates_tags(self) -> None:
        config = """
tags: old;monitoring
net0: name=eth0,bridge=vmbr0,ip=10.10.30.42/24
"""
        with (
            mock.patch.object(IPTAG, "get_guest_config", return_value=config),
            mock.patch.object(IPTAG, "set_guest_tags") as set_guest_tags,
        ):
            changed = IPTAG.reconcile_guest(
                "lxc",
                "100",
                "running",
                {},
                self.settings,
            )

        self.assertTrue(changed)
        set_guest_tags.assert_called_once_with(
            "lxc",
            "100",
            ["42", "old", "monitoring"],
            self.settings,
        )

    def test_reconcile_stopped_lxc_preserves_tags(self) -> None:
        config = "tags: 42;monitoring\n"
        with (
            mock.patch.object(IPTAG, "get_guest_config", return_value=config),
            mock.patch.object(IPTAG, "set_guest_tags") as set_guest_tags,
        ):
            changed = IPTAG.reconcile_guest(
                "lxc",
                "100",
                "stopped",
                {},
                self.settings,
            )

        self.assertFalse(changed)
        set_guest_tags.assert_not_called()


if __name__ == "__main__":
    unittest.main()
