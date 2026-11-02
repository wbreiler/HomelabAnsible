"""Exercise update safety without contacting a guest or changing packages."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'roles/lxc_auto_update/files/lxc-auto-update.py'
SPEC = importlib.util.spec_from_file_location('updater', SOURCE)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class AutoUpdate(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        report = patch.object(updater, 'REPORT_FILE', Path(directory.name) / 'last-run.json')
        report.start()
        self.addCleanup(report.stop)
        self.config = dict(backup_storage='pbs', backup_max_age_hours=8, skip_vmids=[])
        self.guests = [dict(vmid=100, status='running', name='test')]
        self.backups = [dict(vmid=100, subtype='lxc', ctime=1000)]

    def api(self, path, *args):
        if path.endswith('/config'):
            return {}
        return self.backups if path.endswith('/content') else self.guests

    def run_updates(self, **kwargs):
        with patch.object(updater, 'api', side_effect=self.api), patch.object(updater.time, 'time', return_value=1100):
            return updater.update_guests(self.config, **kwargs)

    def test_backup_requires_correct_guest_type_age_and_no_failed_verification(self):
        for changes in ({'vmid': 101}, {'subtype': 'qemu'}, {'ctime': 30000}, {'ctime': -30000},
                        {'verification': {'state': 'failed'}}):
            with self.subTest(changes=changes):
                self.assertFalse(updater.recent_backup([{**self.backups[0], **changes}], 100, 8, 1100))
        self.assertTrue(updater.recent_backup(self.backups, 100, 8, 1100))

    @patch.object(updater, 'guest')
    def test_missing_backup_prevents_guest_commands(self, guest):
        self.backups = []
        self.assertEqual(self.run_updates(), 1)
        guest.assert_not_called()

    @patch.object(updater, 'guest')
    def test_stopped_and_excluded_guests_are_not_started_or_updated(self, guest):
        self.guests += [dict(vmid=101, status='stopped')]
        self.config['skip_vmids'] = [100]
        self.assertEqual(self.run_updates(), 0)
        guest.assert_not_called()

    @patch.object(updater.subprocess, 'run')
    @patch.object(updater, 'guest', return_value='')
    def test_dry_run_only_simulates_guest_package_changes(self, guest, run):
        self.assertEqual(self.run_updates(dry_run=True), 0)
        self.assertIn('--simulate', guest.call_args.args)
        run.assert_not_called()
        self.assertFalse(updater.REPORT_FILE.exists())

    @patch.object(updater, 'guest')
    def test_locked_guest_is_not_updated(self, guest):
        original = self.api
        self.api = lambda path, *args: {'lock': 'backup'} if path.endswith('/config') else original(path, *args)
        self.assertEqual(self.run_updates(), 1)
        guest.assert_not_called()

    @patch.object(updater, 'failed_services', return_value=set())
    @patch.object(updater, 'guest', return_value='')
    @patch.object(updater.subprocess, 'run')
    def test_failed_update_does_not_hide_failure_or_block_other_guests(self, run, guest, failed):
        self.guests += [dict(vmid=101, status='running')]
        self.backups += [dict(vmid=101, subtype='lxc', ctime=1000)]
        run.side_effect = [subprocess.CalledProcessError(100, 'apt-get'), None]
        self.assertEqual(self.run_updates(), 1)
        self.assertEqual(run.call_count, 2)
        results = json.loads(updater.REPORT_FILE.read_text())['results']
        self.assertEqual(results, [{'vmid': 100, 'status': 'failed'}, {'vmid': 101, 'status': 'completed'}])
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:2], ['pct', 'exec'])

    @patch.object(updater, 'failed_services', side_effect=[set(), {'broken.service loaded failed failed'}])
    @patch.object(updater, 'guest', return_value='')
    @patch.object(updater.subprocess, 'run')
    def test_new_service_failure_fails_the_job(self, run, guest, failed):
        self.assertEqual(self.run_updates(), 1)

    def test_unknown_requested_guest_is_an_error(self):
        self.assertEqual(self.run_updates(requested=[999]), 1)

    def test_upgrade_preserves_configuration_and_forbids_package_removal(self):
        self.assertIn('set -eu', updater.UPDATE)
        self.assertIn('APT::Update::Error-Mode=any', updater.UPDATE)
        self.assertIn('--force-confold', updater.UPDATE)
        self.assertIn('--no-remove', updater.UPDATE)
        self.assertNotIn('dist-upgrade', updater.UPDATE)
        self.assertNotIn('autoremove', updater.UPDATE)
        self.assertNotIn('allow-change-held-packages', updater.UPDATE)


if __name__ == '__main__':
    unittest.main()
