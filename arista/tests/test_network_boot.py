import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("network_boot", Path(__file__).parents[1] / "filter_plugins/network_boot.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class NetworkBootTests(unittest.TestCase):
    def setUp(self):
        self.config = {"server": "192.0.2.10", "filename": "netboot.xyz.efi", "new_scopes": [
            {"vlan": 20, "subnet": "198.51.100.0/27", "range": ["198.51.100.24", "198.51.100.30"],
             "gateway": "198.51.100.1", "dns": "192.0.2.1"}]}

    def test_only_adds_boot_options_and_selected_scope(self):
        class TaggedInt(int):
            pass
        self.config["new_scopes"][0]["vlan"] = TaggedInt(20)
        before = copy.deepcopy(self.config)
        result = boot.network_boot_config(self.config)
        self.assertIn("tftp server option 66 ipv4 192.0.2.10", result)
        self.assertIn("interface Vlan20\n   dhcp server ipv4", result)
        self.assertNotIn("reservations", result)
        self.assertNotIn("interface Vlan1\n", result)
        self.assertEqual(self.config, before)

    def test_protected_interfaces_and_duplicate_scopes_are_rejected(self):
        for vlan in (1, 10, 40, 50, "20\ninterface Vlan1"):
            self.config["new_scopes"][0]["vlan"] = vlan
            with self.subTest(vlan=vlan), self.assertRaises(ValueError):
                boot.network_boot_config(self.config)
        self.config["new_scopes"][0]["vlan"] = 20
        self.config["new_scopes"] *= 2
        with self.assertRaises(ValueError):
            boot.network_boot_config(self.config)

    def test_invalid_addresses_ranges_and_filenames_are_rejected(self):
        for fields in ({"range": ["198.51.100.1", "198.51.100.30"]},
                       {"range": ["198.51.100.24", "198.51.100.31"]},
                       {"gateway": "198.51.100.32"}, {"dns": "192.0.2.999"}):
            config = copy.deepcopy(self.config)
            config["new_scopes"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                boot.network_boot_config(config)
        self.config["filename"] = "boot.efi\nno ip routing"
        with self.assertRaises(ValueError):
            boot.network_boot_config(self.config)


if __name__ == "__main__":
    unittest.main()
