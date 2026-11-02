import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "proxy", Path(__file__).resolve().parents[1] / "files/homebridge-mdns-proxy.py"
)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "interface": "br0", "hostname": "bridge.local", "address": "192.0.2.10",
            "services": [{"name": "Paired bridge", "port": 12345,
                          "txt": {"id": "02:00:00:00:00:01", "sf": "0", "c#": "7"}}],
        }

    def test_preserves_advertised_pairing_identity(self):
        self.assertEqual(proxy.validate(copy.deepcopy(self.config)), self.config)

    def test_rejects_unpaired_bridge(self):
        self.config["services"][0]["txt"]["sf"] = "1"
        with self.assertRaises(ValueError):
            proxy.validate(self.config)

    def test_rejects_duplicate_identity_with_different_name(self):
        other = copy.deepcopy(self.config["services"][0])
        other["name"] = "Duplicate bridge"
        self.config["services"].append(other)
        with self.assertRaises(ValueError):
            proxy.validate(self.config)


if __name__ == "__main__":
    unittest.main()
