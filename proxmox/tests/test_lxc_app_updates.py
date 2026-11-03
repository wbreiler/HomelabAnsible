"""Automatic release selection and deployment boundaries, without live hosts."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import mock_open, patch


SOURCE = Path(__file__).resolve().parents[1] / 'roles/lxc_app_updates/files/lxc_app_updates.py'
SPEC = importlib.util.spec_from_file_location('app_updates', SOURCE)
updates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updates)


def release(tag='v1.2.0', **changes):
    return dict(tag_name=tag, published_at='2020-01-01T00:00:00Z', draft=False, prerelease=False, **changes)


class ReleaseSelection(unittest.TestCase):
    def test_major_downgrade_and_zero_minor_are_blocked(self):
        for current, target, allowed in [('1.2.0', '1.3.0', True), ('1.2.0', '2.0.0', False),
                                         ('1.2.0', '1.1.9', False), ('1.2.0', '1.2.0', False),
                                         ('0.12.3', '0.13.0', False), ('0.12.3', '0.12.4', True),
                                         ('1.2.5.7', '1.2.5.8', True),
                                         ('v1.15.0-ls175', 'v1.15.0-ls176', True)]:
            with self.subTest(current=current, target=target):
                self.assertEqual(updates.compatible(current, target), allowed)

    def test_versions_cannot_inject_commands_paths_or_prereleases(self):
        for value in ['1.2.3; reboot', '../1.2.3', '1.2.3-rc1', '1.2.3\nreboot', '1.2.3\n', 'latest', '1.2.3+dev']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                updates.version(value)

    def test_release_selection_respects_stability_and_age(self):
        candidates = [release('v1.2.0'), release('v1.10.0'), release('v2.0.0'),
                      {**release('v1.11.0'), 'prerelease': True},
                      {**release('v1.12.0'), 'draft': True},
                      {**release('v1.13.0'), 'published_at': '2030-01-01T00:00:00Z'}]
        chosen = updates.choose_release(candidates, '1.1.0', 72, 1700000000)
        self.assertEqual(chosen['tag_name'], 'v1.10.0')

    def test_absent_or_malformed_releases_do_not_select_a_target(self):
        self.assertIsNone(updates.choose_release([{}, {'tag_name': '1.2.0'}], '1.1.0', 72, 1700000000))

    def test_credentials_and_plain_http_are_not_downloaded(self):
        for url in ['http://example.com/release', 'https://user:secret@example.com/release', 'file:///tmp/release']:
            with self.subTest(url=url), patch.object(updates.urllib.request, 'urlopen') as fetch, self.assertRaises(ValueError):
                updates.fetch(url)
            fetch.assert_not_called()

    def test_redirects_cannot_expose_registry_tokens_or_downgrade_tls(self):
        request = updates.urllib.request.Request('https://ghcr.io/v2/image', headers={'Authorization': 'Bearer private'})
        handler = updates.HTTPSRedirect()
        for url in ['http://ghcr.io/v2/image', 'https://elsewhere.example/image']:
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, 'redirect', {}, url)

    def test_artifact_digest_is_checked(self):
        response = io.BytesIO(b'artifact')
        response.url = 'https://example.com/release'
        with patch.object(updates, 'fetch', return_value=response), self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            updates.artifact_checksum(response.url, 'sha256:' + '0' * 64)

    def test_package_versions_accept_debian_revisions_but_reject_prereleases(self):
        self.assertEqual(updates.apt_version('1.21.2-1'), (1, 21, 2))
        self.assertEqual(updates.apt_version('2:13.2.4+security1'), (13, 2, 4))
        for value in ['13.3.0~beta1', '14.0.0-rc.1', '13.3.0; reboot']:
            with self.assertRaises(ValueError):
                updates.apt_version(value)


class Deployment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        for name, value in [('STATE', self.state), ('PINS', self.state)]:
            p = patch.object(updates, name, value)
            p.start(); self.addCleanup(p.stop)
        self.config = {'variables': {'private_test': 'do-not-log-this'}, 'minimum_age_hours': 72, 'backup_storage': 'pbs'}
        self.spec = {'repository': 'example/app', 'probe': 'app --version'}
        self.pins = {'app_version': '1.2.0', 'app_release_checksum': 'sha256:' + 'a' * 64}
        for name, value in [('current_version', '1.1.0'), ('json_url', [release()]), ('app_variables', {}),
                            ('resolve_pins', self.pins), ('guest', '')]:
            p = patch.object(updates, name, return_value=value)
            setattr(self, name, p.start()); self.addCleanup(p.stop)

    def update(self, **kwargs):
        return updates.update_one('app', self.spec, {'vmid': 100}, self.config, 'node', **kwargs)

    def test_package_age_survives_runs_and_resets_for_a_new_candidate(self):
        with patch.object(updates.time, 'time', return_value=100000):
            self.assertFalse(updates.package_ready(100, 'alloy', '1.2.3', self.config))
        with patch.object(updates.time, 'time', return_value=400000):
            self.assertTrue(updates.package_ready(100, 'alloy', '1.2.3', self.config))
            self.assertFalse(updates.package_ready(100, 'alloy', '1.2.4', self.config))

    def test_changed_approved_release_or_checksum_blocks_before_backup(self):
        plan = updates.resolve_update('app', self.spec, {'vmid': 100}, self.config, observe=False)
        for key, value in [('current', '0.9.0'), ('target', '1.3.0'), ('pins', {'app_version': '1.2.0'})]:
            with self.subTest(key=key), patch.object(updates, 'backup') as backup, self.assertRaisesRegex(RuntimeError, 'changed after approval'):
                self.update(dry_run=False, approved_plan={**plan, key: value})
            backup.assert_not_called()

    def test_read_only_package_resolution_does_not_write_age_pin(self):
        self.guest.return_value = 'app | 1.2.0 | repo'
        with patch.object(updates, 'apt_candidate', return_value='1.2.0'):
            plan = updates.resolve_update('app', {'package': 'app'}, {'vmid': 100}, self.config, observe=False)
        self.assertIsNone(plan['target'])
        self.assertEqual(list(self.state.iterdir()), [])

    @patch.object(updates, 'backup')
    @patch.object(updates.subprocess, 'run')
    def test_dry_run_does_not_back_up_or_deploy(self, run, backup):
        self.assertEqual(self.update(dry_run=True)['status'], 'planned')
        backup.assert_not_called(); run.assert_not_called()
        self.assertEqual(list(self.state.iterdir()), [])

    @patch.object(updates, 'backup', side_effect=RuntimeError('backup unavailable'))
    @patch.object(updates.subprocess, 'run')
    def test_backup_failure_prevents_deployment(self, run, backup):
        with self.assertRaisesRegex(RuntimeError, 'backup unavailable'):
            self.update(dry_run=False)
        run.assert_not_called()

    @patch.object(updates, 'backup')
    @patch.object(updates.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ansible'))
    def test_failure_blocks_future_unattended_retries(self, run, backup):
        with self.assertRaises(subprocess.CalledProcessError):
            self.update(dry_run=False)
        failure = self.state / 'app-100.failed.json'
        self.assertTrue(failure.exists())
        self.assertNotIn('do-not-log-this', failure.read_text())
        with self.assertRaisesRegex(RuntimeError, 'previous deployment failed'):
            self.update(dry_run=False)
        self.assertEqual(backup.call_count, 1)
        self.assertFalse((self.state / 'app.json').exists())

    @patch.object(updates, 'backup')
    @patch.object(updates.subprocess, 'run')
    def test_success_persists_exact_pins_and_removes_secret_tempfile(self, run, backup):
        self.current_version.side_effect = ['1.1.0', '1.2.0']
        self.assertEqual(self.update(dry_run=False), {
            'app': 'app', 'vmid': 100, 'previous': '1.1.0', 'current': '1.2.0', 'status': 'updated',
        })
        self.assertEqual(json.loads((self.state / 'app.json').read_text()), self.pins)
        self.assertEqual([p.name for p in self.state.iterdir()], ['app.json'])
        argv = run.call_args.args[0]
        self.assertEqual(argv[:3], ['ansible-playbook', '-i', 'node,'])
        self.assertNotIn('do-not-log-this', ' '.join(argv))

    @patch.object(updates, 'backup')
    @patch.object(updates, 'install_native')
    def test_native_update_reports_before_and_verified_installed_versions(self, install, backup):
        self.spec['native'] = True
        self.current_version.side_effect = ['1.1.0', 'v1.2.0']
        result = self.update(dry_run=False)
        self.assertEqual((result['previous'], result['current'], result['status']), ('1.1.0', 'v1.2.0', 'updated'))
        install.assert_called_once()

    def test_package_reports_keep_each_previous_version_and_only_changed_packages(self):
        previous = {'grafana': '13.2.4-1', 'loki': '3.7.8', 'alloy': '1.14.0'}
        targets = {'grafana': '13.3.0-1', 'loki': '3.7.9'}
        self.config['packages'] = list(previous)

        def guest(vmid, *args):
            if args[0] == 'apt-cache':
                return f'{args[-1]} | {targets.get(args[-1], previous[args[-1]])} | repository'
            if args[0] == 'dpkg-query':
                return targets[args[-1]]
            return ''

        for dry_run in [True, False]:
            with self.subTest(dry_run=dry_run), patch.object(updates, 'run', side_effect=lambda args, **kw: previous[args[-1]]), \
                    patch.object(updates, 'guest', side_effect=guest), patch.object(updates, 'backup') as backup, \
                    patch.object(updates, 'apt_candidate', side_effect=[*targets.values(), None]), \
                    patch.object(updates, 'package_ready', return_value=True), patch.object(updates.subprocess, 'run') as run:
                result = updates.update_packages({'vmid': 100}, self.config, 'node', dry_run, False)
                self.assertEqual(result, {
                    'app': 'packages', 'vmid': 100, 'status': 'planned' if dry_run else 'updated',
                    'previous': {'grafana': '13.2.4-1', 'loki': '3.7.8'}, 'targets': targets,
                })
                self.assertEqual(backup.call_count, 0 if dry_run else 1)
                self.assertEqual(run.call_count, 0 if dry_run else 1)

    def test_package_approval_rejects_changed_versions_before_backup(self):
        self.config['packages'] = ['grafana']
        with patch.object(updates, 'run', return_value='13.2.4-1'), \
                patch.object(updates, 'guest', return_value='grafana | 13.3.1-1 | repo'), \
                patch.object(updates, 'apt_candidate', return_value='13.3.1-1'), \
                patch.object(updates, 'package_ready', return_value=True), \
                patch.object(updates, 'backup') as backup, patch.object(updates.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'changed after approval'):
                updates.update_packages({'vmid': 100}, self.config, 'node', False, False,
                                        approved_plan={'previous': {'grafana': '13.2.4-1'}, 'targets': {'grafana': '13.3.0-1'}})
        backup.assert_not_called()
        run.assert_not_called()

    @patch.object(updates, 'backup')
    @patch.object(updates.subprocess, 'run')
    def test_current_release_does_not_trigger_a_restart(self, run, backup):
        self.json_url.return_value = []
        self.assertEqual(self.update(dry_run=False)['status'], 'current')
        backup.assert_not_called(); run.assert_not_called()

    @patch.object(updates, 'backup')
    def test_current_version_does_not_hide_a_previous_health_failure(self, backup):
        (self.state / 'app-100.failed.json').write_text('{}')
        self.json_url.return_value = []
        with self.assertRaisesRegex(RuntimeError, 'repair and verify health'):
            self.update(dry_run=False, retry_failed=True)
        backup.assert_not_called()


class ArtifactResolution(unittest.TestCase):
    def test_app_and_package_results_keep_guest_names_even_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.json').write_text(json.dumps({'roles': ['app'], 'exclude': [], 'packages': []}))
            (root / 'catalog.yml').write_text('app: {}')
            guest = {'vmid': 100, 'name': 'test-guest', 'status': 'running'}
            for status in ['updated', 'current', 'failed']:
                with self.subTest(status=status), patch.object(updates, 'ROOT', root), patch.object(updates, 'STATE', root), \
                        patch.object(updates, 'api', return_value=[guest]), patch.object(updates.fcntl, 'flock'), \
                        patch('builtins.open', mock_open()), patch('sys.argv', ['updater']), patch.object(updates.os, 'umask'), \
                        patch.object(updates, 'app_variables', return_value={'app_hostname': 'test-guest'}), \
                        patch.object(updates, 'update_one', return_value={'app': 'app', 'vmid': 100, 'status': status}) as app, \
                        patch.object(updates, 'update_packages', return_value={'app': 'packages', 'vmid': 100, 'status': status}) as packages:
                    if status == 'failed':
                        app.side_effect = packages.side_effect = RuntimeError('update failed')
                    self.assertEqual(updates.main(), int(status == 'failed'))
                    results = json.loads((root / 'last-run.json').read_text())['results']
                    self.assertEqual(len(results), 2)
                    self.assertEqual([row['app'] for row in results], ['app', 'packages'])
                    for row in results:
                        self.assertEqual((row['vmid'], row['name'], row['status']), (100, 'test-guest', status))

    def test_service_reports_track_invocation_but_dry_run_plans_stay_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config.json').write_text(json.dumps({'roles': [], 'packages': []}))
            (root / 'catalog.yml').write_text('{}')
            for flags, filename in [([], 'last-run.json'), (['--dry-run'], 'plan.json')]:
                with patch.object(updates, 'ROOT', root), patch.object(updates, 'STATE', root), \
                        patch.object(updates, 'api', return_value=[]), patch.object(updates.fcntl, 'flock'), \
                        patch('builtins.open', mock_open()), patch('sys.argv', ['updater', *flags]), \
                        patch.dict(updates.os.environ, {'INVOCATION_ID': 'current-run'}), patch.object(updates.os, 'umask'):
                    self.assertEqual(updates.main(), 0)
                report = json.loads((root / filename).read_text())
                self.assertEqual(report, [] if flags else {'invocation_id': 'current-run', 'results': []})

    def test_backup_rechecks_guest_state_and_uses_proxmox_file_mask(self):
        with patch.object(updates, 'api', side_effect=[{'status': 'running'}, {}]), patch.object(updates.subprocess, 'run') as run:
            updates.backup(100, {'backup_storage': 'pbs'}, 'node')
            self.assertEqual(run.call_args.kwargs['umask'], 0o022)
        with patch.object(updates, 'api', return_value={'status': 'stopped'}), patch.object(updates.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'moved or stopped'):
                updates.backup(100, {'backup_storage': 'pbs'}, 'node')
            run.assert_not_called()

    def test_next_release_does_not_reuse_previous_literal_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = root / 'roles/app/defaults'
            defaults.mkdir(parents=True)
            (defaults / 'main.yml').write_text('app_release_url: https://example.com/v{{ app_version }}/app.tar.gz\n')
            with patch.object(updates, 'ROOT', root), patch.object(updates, 'artifact_checksum', return_value='sha256:abc'):
                pins = updates.resolve_pins('app', {}, {'app_release_url': 'https://example.com/v1.1.0/app.tar.gz'}, release())
            self.assertEqual(pins['app_release_url'], 'https://example.com/v1.2.0/app.tar.gz')


if __name__ == '__main__':
    unittest.main()
