"""Check LANCache DNS, client access, and private worker networking."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml


class LANCacheTests(unittest.TestCase):
    def test_dns_and_cache_share_networks_without_host_ports(self):
        playbook = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / 'playbooks/lancache.yml').read_text()
        )
        desired = playbook[0]['tasks'][-1]['vars']['desired_app']
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            json.dumps(desired['custom_compose_config'])
        ).render(
            lancache_bind_address='192.0.2.11',
            lancache_network_name='storage-macvlan',
            lancache_prefill_network_name='lancache-workers',
            lancache_prefill_subnet='172.30.0.0/24',
            lancache_prefill_address='172.30.0.2',
            lancache_root='/mnt/tank/appdata/lancache',
            lancache_upstream_dns='1.1.1.1',
        )
        compose = yaml.safe_load(rendered)
        dns = compose['services']['dns']
        cache = compose['services']['monolithic']
        self.assertEqual(dns['network_mode'], 'service:monolithic')
        self.assertIn('monolithic', dns['depends_on'])
        self.assertEqual(dns['environment']['LANCACHE_IP'],
                         cache['networks']['cache']['ipv4_address'])
        for service in compose['services'].values():
            self.assertNotIn('ports', service)
        self.assertEqual(compose['networks']['cache'],
                         {'external': True, 'name': 'storage-macvlan'})
        self.assertEqual(cache['networks']['prefill']['ipv4_address'], '172.30.0.2')
        self.assertEqual(cache['networks']['cache']['gw_priority'], 1)
        self.assertEqual(compose['networks']['prefill']['name'], 'lancache-workers')
        self.assertEqual(compose['networks']['prefill']['driver'], 'bridge')
        self.assertEqual(cache['volumes'], [
            '/mnt/tank/appdata/lancache/cache:/data/cache',
            '/mnt/tank/appdata/lancache/logs:/data/logs',
        ])

    def test_prefill_workers_keep_accounts_and_use_distinct_macvlan_addresses(self):
        compose = yaml.safe_load(
            (Path(__file__).resolve().parents[1] /
             'files/lancache/prefill.compose.yml').read_text()
        )
        self.assertTrue(compose['networks']['cache']['external'])
        self.assertEqual(compose['networks']['cache']['name'],
                         '${LANCACHE_NETWORK:?Set LANCACHE_NETWORK}')
        addresses = []
        for name in ['steam', 'epic']:
            worker = compose['services'][name]
            self.assertEqual(worker['dns'], ['${LANCACHE_IP:?Set LANCACHE_IP}'])
            self.assertEqual(worker['volumes'], [f'{name}-config:/Config'])
            self.assertEqual(worker['logging']['driver'], 'none')
            self.assertNotIn('ports', worker)
            self.assertNotIn('network_mode', worker)
            addresses.append(worker['networks']['cache']['ipv4_address'])
        self.assertEqual(len(set(addresses)), 2)


if __name__ == '__main__':
    unittest.main()
