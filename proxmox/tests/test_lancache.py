"""Check the staged and production Compose models without a Docker daemon."""
from pathlib import Path
import unittest

import jinja2
import yaml


class LANCacheTest(unittest.TestCase):
    def test_dashboard_only_mounts_migrated_database_in_full_phase(self):
        role = Path(__file__).resolve().parents[1] / "roles/lancache"
        settings = yaml.safe_load((role / "defaults/main.yml").read_text())
        settings.update(
            ansible_facts={"default_ipv4": {"interface": "ens18"}},
            lancache_subnet="192.0.2.0/27",
            lancache_gateway="192.0.2.1",
            lancache_cache_ip="192.0.2.11",
            lancache_dashboard_ip="192.0.2.14",
            lancache_upstream_dns="192.0.2.1",
            lancache_worker_subnet="172.30.0.0/24",
            lancache_worker_cache_ip="172.30.0.2",
            lancache_worker_dashboard_ip="172.30.0.3",
        )
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            (role / "templates/compose.yml.j2").read_text()
        )
        for phase in ("cache", "full"):
            settings["lancache_phase"] = phase
            services = yaml.safe_load(template.render(settings))["services"]
            self.assertEqual("dashboard" in services, phase == "full")
            self.assertEqual(services["dns"]["network_mode"], "service:monolithic")
            self.assertIn("/srv/lancache/cache:/data/cache", services["monolithic"]["volumes"])
            if phase == "full":
                self.assertIn("/srv/lancache/dashboard:/data", services["dashboard"]["volumes"])
                self.assertEqual(services["dashboard"]["environment"]["PUID"], "33")


if __name__ == "__main__":
    unittest.main()
