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
            lancache_worker_dns_ip="172.30.0.10",
            lancache_nginx_config_checksum="nginx-test-checksum",
            lancache_haproxy_config_checksum="haproxy-test-checksum",
            lancache_postgres_config_checksum="postgres-test-checksum",
            lancache_epic_prefill_image="sha256:" + "0" * 64,
        )
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            (role / "templates/compose.yml.j2").read_text()
        )
        for phase in ("cache", "full"):
            settings["lancache_phase"] = phase
            services = yaml.safe_load(template.render(settings))["services"]
            self.assertEqual("dashboard" in services, phase == "full")
            self.assertEqual("worker-dns" in services, phase == "full")
            self.assertEqual(services["dns"]["network_mode"], "service:monolithic")
            upstream = services["upstream"]
            self.assertEqual(upstream["network_mode"], "service:monolithic")
            self.assertNotIn("ports", upstream)
            self.assertTrue(upstream["read_only"])
            self.assertEqual(upstream["cap_drop"], ["ALL"])
            self.assertIn("@sha256:", upstream["image"])
            self.assertEqual(services["monolithic"]["labels"]["homelab.lancache-proxy-config"], "nginx-test-checksum")
            self.assertEqual(upstream["labels"]["homelab.lancache-proxy-config"], "haproxy-test-checksum")
            self.assertIn("/srv/lancache/cache:/data/cache", services["monolithic"]["volumes"])
            self.assertIn("/opt/lancache/nginx-upstream.conf:/etc/lancache-upstream.conf:ro", services["monolithic"]["volumes"])
            self.assertIn("/opt/lancache/nginx-cache-upstream.conf:/etc/lancache-cache-upstream.conf:ro", services["monolithic"]["volumes"])
            self.assertIn("/opt/lancache/upstream-hook.sh:/hooks/entrypoint-pre.d/99_upstream.sh:ro", services["monolithic"]["volumes"])
            if phase == "full":
                self.assertIn("/srv/lancache/dashboard:/data", services["dashboard"]["volumes"])
                self.assertIn("/opt/lancache/postgres-environment:/etc/environment:ro", services["dashboard"]["volumes"])
                self.assertEqual(services["dashboard"]["environment"]["PUID"], "33")
                connection = services["dashboard"]["environment"]["ConnectionStrings__DefaultConnection"]
                self.assertIn("Command Timeout=120", connection)
                self.assertNotIn("Password=", connection)
                # Workers cannot reach the guest's public macvlan address.
                self.assertEqual(set(services["worker-dns"]["networks"]), {"workers"})
                self.assertNotIn("ports", services["worker-dns"])
                self.assertEqual(services["worker-dns"]["environment"]["LANCACHE_IP"], settings["lancache_worker_cache_ip"])
                self.assertEqual(services["dns"]["environment"]["LANCACHE_IP"], settings["lancache_cache_ip"])
                self.assertEqual(services["dashboard"]["environment"]["Prefill__LancacheDnsIp"], settings["lancache_worker_dns_ip"])


if __name__ == "__main__":
    unittest.main()
