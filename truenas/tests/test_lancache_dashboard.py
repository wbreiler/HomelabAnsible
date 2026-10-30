"""Check manager mounts and log rotation configuration."""
import json
from pathlib import Path
import unittest

import jinja2
import yaml


class DashboardTests(unittest.TestCase):
    def test_management_mounts(self):
        play = yaml.safe_load((Path(__file__).resolve().parents[1] /
                               'playbooks/lancache-dashboard.yml').read_text())[0]
        compose = play['tasks'][-1]['vars']['desired_app']['custom_compose_config']
        compose = yaml.safe_load(jinja2.Environment(
            undefined=jinja2.StrictUndefined).from_string(json.dumps(compose)).render(
                lancache_root='/mnt/tank/appdata/lancache',
                lancache_dashboard_root='/mnt/tank/appdata/lancache/dashboard',
                lancache_dashboard_address='192.0.2.14',
                lancache_network_name='storage-macvlan',
                lancache_bind_address='192.0.2.11',
                lancache_prefill_network_name='lancache-workers',
                lancache_prefill_address='172.30.0.2',
                lancache_dashboard_prefill_address='172.30.0.3'))
        app = compose['services']['dashboard']
        self.assertRegex(app['image'], r'@sha256:[0-9a-f]{64}$')
        self.assertNotIn('ports', app)
        self.assertNotIn('privileged', app)
        self.assertNotIn('network_mode', app)
        mounts = {mount.split(':')[1]: mount for mount in app['volumes']}
        for target in ['/cache', '/logs', '/var/run/docker.sock']:
            self.assertTrue(mounts[target].endswith(':rw'))
        self.assertTrue(mounts['/settings/lancache.env'].endswith(':ro'))
        self.assertEqual(app['environment']['LanCache__CachePath'], '/cache/cache')
        self.assertEqual(app['environment']['NginxLogRotation__Enabled'], 'true')
        self.assertEqual(app['environment']['NginxLogRotation__ContainerName'],
                         'ix-lancache-monolithic-1')
        self.assertEqual(app['networks']['cache']['ipv4_address'], '192.0.2.14')
        self.assertTrue(compose['networks']['cache']['external'])
        self.assertEqual(app['dns'], ['192.0.2.11'])
        self.assertEqual(app['environment']['Prefill__NetworkMode'], 'lancache-workers')
        self.assertEqual(app['environment']['Prefill__LancacheIp'], '172.30.0.2')
        self.assertEqual(app['environment']['Prefill__LancacheDnsIp'], '172.30.0.2')
        self.assertEqual(app['networks']['prefill']['ipv4_address'], '172.30.0.3')
        self.assertEqual(compose['networks']['prefill'],
                         {'external': True, 'name': 'lancache-workers'})


if __name__ == '__main__':
    unittest.main()
