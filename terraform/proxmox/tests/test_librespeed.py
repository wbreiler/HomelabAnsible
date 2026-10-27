"""LibreSpeed integration with the guarded guest workflow."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy_guest', MODULE / 'scripts/deploy_guest.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class LibreSpeedTests(unittest.TestCase):
    def test_profile_routes_only_to_librespeed(self):
        profile = deploy.validate(dict(
            name='lan-speedtest', kind='lxc', app='librespeed', node_name='test-node',
            vlan_id=40, ipv4_address='192.0.2.10/24', gateway='192.0.2.1',
            dns_servers=['192.0.2.1'], ssh_public_key_file=str(MODULE / 'tests/install.pub'),
            template_file_id='local:vztmpl/debian-test.tar.zst'))
        self.assertEqual(deploy.APPS[profile['app']][0], 'librespeed-guests.yml')
        with tempfile.TemporaryDirectory() as directory:
            groups = deploy.inventory(profile, Path(directory))['all']['children']
        self.assertEqual(set(groups), {'librespeed_guests'})
        host = groups['librespeed_guests']['hosts']['lan_speedtest']
        self.assertEqual(host['terraform_guest_name'], 'lan-speedtest')
        self.assertEqual(host['ansible_host'], '192.0.2.10')
