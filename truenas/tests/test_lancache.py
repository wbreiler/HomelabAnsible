"""Check that LANCache shares one address without host port bindings."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml


class LANCacheTests(unittest.TestCase):
    def test_services_share_only_the_dedicated_address(self):
        playbook = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / 'playbooks/lancache.yml').read_text()
        )
        desired = playbook[0]['tasks'][-1]['vars']['desired_app']
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            json.dumps(desired['custom_compose_config'])
        ).render(
            lancache_bind_address='192.0.2.11',
            lancache_network_name='storage-macvlan',
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
        self.assertEqual(cache['volumes'], [
            '/mnt/tank/appdata/lancache/cache:/data/cache',
            '/mnt/tank/appdata/lancache/logs:/data/logs',
        ])


if __name__ == '__main__':
    unittest.main()
