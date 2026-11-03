import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("unifi_pxe", Path(__file__).parents[1] / "files/unifi_pxe.py")
pxe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pxe)


class PxePlanTests(unittest.TestCase):
    def setUp(self):
        self.network = {"_id": "test", "name": "Example", "purpose": "corporate",
                        "vlan_enabled": True, "vlan": 70, "dhcpd_enabled": True,
                        "ip_subnet": "192.0.2.1/24", "custom_setting": "preserve"}
        self.config = {"server": "192.0.2.10", "filename": "netboot.xyz.efi", "networks": [{"vlan": 70}]}

    def test_patch_is_narrow_and_idempotent(self):
        before = copy.deepcopy(self.network)
        [(original, patch)] = pxe.plan(self.config, [self.network])
        self.assertEqual(set(patch), {"dhcpd_boot_enabled", "dhcpd_boot_server", "dhcpd_boot_filename"})
        self.assertEqual(self.network, before)
        self.assertEqual(pxe.plan(self.config, [dict(original, **patch)]), [])

    def test_external_dhcp_relay_and_disabled_networks_are_rejected(self):
        for fields in ({"purpose": "vlan-only"}, {"dhcp_relay_enabled": True},
                       {"enabled": False}, {"dhcpd_enabled": False}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                pxe.plan(self.config, [dict(self.network, **fields)])

    def test_explicit_range_excludes_gateway_and_subnet_boundaries(self):
        self.network["dhcpd_enabled"] = False
        for limits in (["192.0.2.0", "192.0.2.20"], ["192.0.2.1", "192.0.2.20"],
                       ["192.0.2.20", "192.0.2.255"], ["192.0.3.20", "192.0.3.30"],
                       ["192.0.2.30", "192.0.2.20"]):
            self.config["networks"][0]["dhcp_range"] = limits
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                pxe.plan(self.config, [self.network])
        self.config["networks"][0]["dhcp_range"] = ["192.0.2.20", "192.0.2.30"]
        self.assertTrue(pxe.plan(self.config, [self.network])[0][1]["dhcpd_enabled"])

    def test_invalid_filename_and_duplicate_target_are_rejected(self):
        for name in ("netboot.xyz.kpxe ", "../boot.efi", "boot\n.efi"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                pxe.plan(dict(self.config, filename=name), [self.network])
        self.config["networks"] *= 2
        with self.assertRaises(ValueError):
            pxe.plan(self.config, [self.network])


if __name__ == "__main__":
    unittest.main()
