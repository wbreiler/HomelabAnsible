"""Validate the ISO app's storage and network boundaries without Docker."""
import ipaddress
import json
from pathlib import Path
import unittest

import jinja2
import yaml


class IsoServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1] / "files" / "iso-server"
        cls.settings = yaml.safe_load((root / "vars.yml.example").read_text())
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        environment.filters["to_json"] = json.dumps
        cls.compose = yaml.safe_load(
            environment.from_string((root / "docker-compose.yml.j2").read_text())
            .render(cls.settings)
        )

    def test_storage_cannot_be_created_or_modified(self):
        app = self.compose["services"]["iso-server"]
        self.assertTrue(app["read_only"])
        self.assertNotEqual(app["user"].split(":")[0], "0")
        self.assertEqual(app["cap_drop"], ["ALL"])
        mount = app["volumes"][0]
        self.assertEqual(mount["source"], self.settings["iso_server_root"])
        self.assertTrue(mount["read_only"])
        self.assertFalse(mount["bind"]["create_host_path"])

    def test_dedicated_address_never_publishes_host_ports(self):
        app = self.compose["services"]["iso-server"]
        self.assertNotIn("ports", app)
        network = self.compose["networks"]["iso-storage"]
        self.assertEqual(network["driver"], "macvlan")
        ipam = network["ipam"]["config"][0]
        address = ipaddress.ip_address(app["networks"]["iso-storage"]["ipv4_address"])
        self.assertIn(address, ipaddress.ip_network(ipam["subnet"]))
        self.assertNotEqual(str(address), ipam["gateway"])
        pool = ipaddress.ip_network(ipam["ip_range"])
        self.assertEqual(pool.num_addresses, 1)
        self.assertIn(address, pool)


if __name__ == "__main__":
    unittest.main()
