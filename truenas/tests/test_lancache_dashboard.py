"""Check that dashboard monitoring cannot modify the cache or control Docker."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml


class DashboardTests(unittest.TestCase):
    def test_monitoring_boundaries(self):
        play = yaml.safe_load((Path(__file__).resolve().parents[1] /
                               'playbooks/lancache-dashboard.yml').read_text())[0]
        compose = play['tasks'][-1]['vars']['desired_app']['custom_compose_config']
        compose = yaml.safe_load(jinja2.Environment(
            undefined=jinja2.StrictUndefined).from_string(json.dumps(compose)).render(
                lancache_root='/mnt/tank/appdata/lancache',
                lancache_dashboard_root='/mnt/tank/appdata/lancache/dashboard',
                lancache_dashboard_address='192.0.2.14',
                lancache_network_name='storage-macvlan'))
        app = compose['services']['dashboard']
        self.assertRegex(app['image'], r'@sha256:[0-9a-f]{64}$')
        self.assertNotIn('ports', app)
        self.assertNotIn('privileged', app)
        self.assertNotIn('network_mode', app)
        self.assertFalse(any('docker.sock' in mount for mount in app['volumes']))
        mounts = {mount.split(':')[1]: mount for mount in app['volumes']}
        for target in ['/cache', '/logs', '/settings/lancache.env']:
            self.assertTrue(mounts[target].endswith(':ro'))
        self.assertEqual(app['environment']['LanCache__CachePath'], '/cache/cache')
        self.assertEqual(app['environment']['NginxLogRotation__Enabled'], 'false')
        self.assertEqual(app['networks']['cache']['ipv4_address'], '192.0.2.14')
        self.assertTrue(compose['networks']['cache']['external'])


if __name__ == '__main__':
    unittest.main()
