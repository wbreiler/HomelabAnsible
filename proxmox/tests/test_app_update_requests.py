"""Approval binding, crash recovery, and fixed app update boundaries."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'roles/maintenance_queries/files/homelab-status.py'
SPEC = importlib.util.spec_from_file_location('update_queries', SOURCE)
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)
u = q.app_updates
b = u.backend
OWNER, BOT, CHANNEL, MESSAGE, REPLY = [str(n) * 18 for n in range(1, 6)]
PLAN = {'backend': 'lxc', 'app': 'sonarr', 'label': 'sonarr: 1.0.0 → 1.1.0', 'effect': 'Back up, then restart this app.'}


class Requests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'node': 'node', 'platform': 'pve', 'state_dir': str(self.root), 'app_updates_enabled': True,
                       'owner_user_id': OWNER, 'bot_user_id': BOT, 'channel_id': CHANNEL}
        self.message = {'id': MESSAGE, 'channel_id': CHANNEL, 'type': 0, 'author': {'id': OWNER},
                        'mentions': [{'id': BOT}], 'content': '<@' + BOT + '> update sonarr on node'}
        self.display = ''
        self.reactions = set()
        self.sent = []
        self.patch('implementation', return_value='code')
        self.prepare = patch.object(b, 'prepare', return_value=copy.deepcopy(PLAN)).start()
        self.addCleanup(patch.stopall)
        self.discord = patch.object(q, 'discord', side_effect=self.send).start()

    def patch(self, name, **kwargs):
        return patch.object(u, name, **kwargs).start()

    def send(self, config, method='GET', suffix='', payload=None):
        self.sent.append((method, suffix, payload))
        if '/reactions/' in suffix:
            if method == 'PUT':
                return None
            return [{'id': OWNER}] if any(u.urllib.parse.quote(e, safe='') in suffix for e in self.reactions) else []
        if method in ('POST', 'PATCH'):
            self.assertEqual(payload['allowed_mentions'], {'parse': []})
            self.display = payload['content']
        return {'id': REPLY, 'channel_id': CHANNEL, 'author': {'id': BOT}, 'content': self.display}

    def prepare_proposal(self):
        u.request(q, self.config, self.message)
        self.assertEqual(u.read(self.config)['status'], 'proposed')
        self.assertIn('Approve one app update', self.display)

    def approve(self):
        self.prepare_proposal()
        self.reactions.add('✅')
        with patch.object(u, 'start') as start:
            u.poll(q, self.config)
        start.assert_called_once()
        self.assertEqual(u.read(self.config)['status'], 'approved')

    def test_strict_command_and_owner_routing(self):
        self.assertEqual(q.intent(self.message, self.config), 'app_update')
        self.assertEqual(u.parse(self.message['content']), ('sonarr', 'node'))
        self.assertEqual(u.parse('update deluge/gluetun on erebus'), ('deluge/gluetun', 'erebus'))
        for text in ['check for updates', 'update all', 'update sonarr on node; reboot', 'update ../../x on node',
                     'update sonarr on node\nrestart all']:
            self.assertIsNone(u.parse(text))
        self.assertIsNone(q.intent({**self.message, 'author': {'id': BOT}}, self.config))
        self.assertEqual(q.intent({**self.message, 'content': '<@' + BOT + '> check for updates'}, self.config), 'updates')

    def test_other_host_does_not_prepare_or_reply(self):
        u.request(q, {**self.config, 'node': 'other'}, self.message)
        self.prepare.assert_not_called()
        self.discord.assert_not_called()

    def test_apps_and_os_use_the_existing_batch_approval_flow(self):
        for scope in ('apps', 'os', 'all'):
            with self.subTest(scope=scope), patch.object(u.batches, 'request') as request:
                message = {**self.message, 'content': '<@' + BOT + '> update ' + scope + ' on node'}
                self.assertEqual(q.intent(message, self.config), 'app_update')
                u.request(q, self.config, message)
                request.assert_called_once_with(q, self.config, message, 'node', scope=scope)
        self.prepare.assert_not_called()

    def test_update_request_bypasses_inspection_and_ai_counters(self):
        now_id = str((int(time.time() * 1000) - 1420070400000) << 22)
        message = {**self.message, 'id': now_id}
        state = {'day': time.strftime('%Y-%m-%d', time.gmtime()), 'calls': 7, 'checks': 20,
                 'cursor': str(int(now_id) - 1)}
        self.discord.side_effect = None
        self.discord.return_value = [message]
        with patch.object(u, 'poll'), patch.object(u, 'request') as request, patch.object(q, 'collect') as collect:
            q.poll(self.config, state, self.root / 'state.json')
        request.assert_called_once()
        collect.assert_not_called()
        self.assertEqual((state['calls'], state['checks']), (7, 20))
        self.assertEqual(state['cursor'], now_id)

    def test_proposal_is_read_only_and_edits_one_message(self):
        with patch.object(b, 'perform') as perform, patch.object(u, 'start') as start:
            self.prepare_proposal()
            u.poll(q, self.config)
            u.request(q, self.config, self.message)
        perform.assert_not_called()
        start.assert_not_called()
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.sent), 1)
        self.assertIn('Model: none', self.display)
        self.assertEqual(u.state_path(self.config).stat().st_mode & 0o777, 0o600)

    def test_cancel_wins_over_approval(self):
        self.prepare_proposal()
        self.reactions.update(('✅', '❌'))
        with patch.object(u, 'start') as start:
            u.poll(q, self.config)
        start.assert_not_called()
        self.assertEqual(u.read(self.config)['status'], 'closed')

    def test_early_approval_explains_how_to_rearm_without_starting(self):
        self.reactions.add('✅')
        self.prepare_proposal()
        with patch.object(u, 'start') as start:
            u.poll(q, self.config)
            self.assertIn('Remove your early ✅', self.display)
            self.assertFalse(u.read(self.config).get('armed'))
            start.assert_not_called()
            self.reactions.clear()
            u.poll(q, self.config)
            self.assertTrue(u.read(self.config)['armed'])
            self.assertNotIn('Remove your early ✅', self.display)
            self.reactions.add('✅')
            u.poll(q, self.config)
        start.assert_called_once()

    def test_code_change_during_preparation_never_proposes_an_update(self):
        with patch.object(u, 'implementation', side_effect=['before', 'after']), patch.object(u, 'start') as start:
            u.request(q, self.config, self.message)
        self.assertEqual(u.read(self.config)['status'], 'closed')
        self.assertIn('changed', self.display)
        self.assertNotIn('Approve one app update', self.display)
        start.assert_not_called()

    def test_executor_preserves_controller_delivery_state(self):
        self.approve()
        self.config['platform'] = 'truenas'
        observations = []
        def perform(config, plan, versions, progress):
            current = u.read(config)
            current['notification_lost'] = True
            u.save(q, config, current)
            self.discord.reset_mock()
            progress('Verifying this one attempt.')
            observations.append(u.read(config).get('notification_lost'))
            return 'Completed exactly once.'
        with patch.object(b, 'BACKUP_ROOT', self.root), patch.object(b, 'perform', side_effect=perform) as work:
            u.execute(q, self.config)
            u.execute(q, self.config)
        self.assertEqual(observations, [True])
        self.assertTrue(u.read(self.config)['notification_lost'])
        self.assertEqual(u.read(self.config)['outcome'], 'Completed exactly once.')
        work.assert_called_once()
        self.discord.assert_not_called()

    def test_executor_never_overwrites_a_different_request(self):
        for notify in [False, True]:
            with self.subTest(progress=notify):
                u.state_path(self.config).unlink(missing_ok=True)
                self.reactions.clear()
                self.approve()
                self.config['platform'] = 'truenas'
                replacement = {'id': '9' * 18, 'status': 'preparing'}
                continued = []
                def perform(config, plan, versions, progress):
                    u.save(q, config, replacement)
                    if notify:
                        progress('Must not edit the replacement request.')
                    continued.append(True)
                    return 'Finished old attempt.'
                with patch.object(b, 'BACKUP_ROOT', self.root), patch.object(b, 'perform', side_effect=perform), \
                        self.assertRaisesRegex(b.Refused, 'request changed'):
                    u.execute(q, self.config)
                self.assertEqual(u.read(self.config), replacement)
                self.assertEqual(continued, [] if notify else [True])

    def test_deleted_proposal_closes_without_replacement_or_execution(self):
        self.prepare_proposal()
        error = u.urllib.error.HTTPError('https://discord.com', 404, 'deleted', {}, None)
        self.addCleanup(error.close)
        self.discord.side_effect = error
        with patch.object(u, 'start') as start:
            u.poll(q, self.config)
        start.assert_not_called()
        self.assertEqual(u.read(self.config)['status'], 'closed')
        self.assertTrue(u.read(self.config)['notification_lost'])

    def test_expired_or_changed_proposal_never_starts(self):
        for change in ['expires', 'plan', 'code', 'display', 'owner', 'disabled']:
            with self.subTest(change=change):
                u.state_path(self.config).unlink(missing_ok=True)
                self.prepare_proposal()
                item = u.read(self.config)
                config = dict(self.config)
                if change == 'expires': item['expires'] = 0
                if change == 'plan': item['plan']['app'] = 'other'
                if change == 'code': item['code_hash'] = 'other'
                if change == 'display': self.display = 'tampered'
                if change == 'owner': config['owner_user_id'] = '9' * 18
                if change == 'disabled': config['app_updates_enabled'] = False
                u.save(q, self.config, item)
                self.reactions.add('✅')
                with patch.object(u, 'start') as start:
                    u.poll(q, config)
                start.assert_not_called()

    def test_removed_approval_blocks_executor(self):
        self.approve()
        self.reactions.clear()
        with patch.object(b, 'perform') as perform:
            u.execute(q, self.config)
        perform.assert_not_called()
        self.assertEqual(u.read(self.config)['status'], 'closed')

    def test_interrupted_attempt_is_not_replayed(self):
        self.approve()
        self.config['platform'] = 'truenas'
        with patch.object(b, 'BACKUP_ROOT', self.root), patch.object(b, 'perform', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                u.execute(q, self.config)
        self.assertEqual(u.read(self.config)['status'], 'executing')
        with patch.object(b, 'perform') as perform:
            u.execute(q, self.config)
        perform.assert_not_called()

    def test_finished_attempt_has_one_reply_and_no_second_execution(self):
        self.approve()
        self.config['platform'] = 'truenas'
        with patch.object(b, 'BACKUP_ROOT', self.root), patch.object(b, 'perform', return_value='Verified exact image.') as perform:
            u.execute(q, self.config)
            u.execute(q, self.config)
        perform.assert_called_once()
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.sent), 1)
        self.assertIn('Verified exact image.', self.display)


class TrueNAS(unittest.TestCase):
    def setUp(self):
        self.original = {'services': {'main': {'image': 'ghcr.io/test/app:1.0.0', 'environment': {'TOKEN': 'private'}},
                                      'sidecar': {'image': 'ghcr.io/test/sidecar:1.0.0'}}}
        self.images = [{'app': 'app', 'service': service, 'ref': value['image'], 'image_id': 'sha256:' + str(i) * 64,
                        'os': 'linux', 'arch': 'amd64', 'digests': [value['image'].split(':')[0] + '@sha256:' + str(i) * 64]}
                       for i, (service, value) in enumerate(self.original['services'].items(), 1)]
        self.versions = MagicMock()
        self.versions.docker_inventory.return_value = self.images
        self.versions.image_update.return_value = {'current': '1.0.0', 'latest': '1.1.0', 'available': '1.1.0',
                                                  'checked_image': 'ghcr.io/test/app:1.1.0', 'target_digest': 'sha256:' + 'a' * 64}
        self.versions.command.side_effect = [json.dumps({'digest': 'sha256:' + 'a' * 64}),
                                            json.dumps({'config': {'digest': 'sha256:' + 'b' * 64}})]
        self.nas = patch.object(b, 'nas_call', side_effect=lambda method, *a, **k: copy.deepcopy(self.original) if method == 'app.config'
                               else {'state': 'RUNNING', 'custom_app': True}).start()
        patch.object(b, 'backup_receipt', return_value='2026-11-03T10:00:00+00:00').start()
        self.addCleanup(patch.stopall)

    def test_only_one_image_changes_and_secrets_never_enter_proposal(self):
        plan = b.prepare_nas({'platform': 'truenas'}, 'app/main', self.versions)
        self.assertEqual(plan['desired']['services']['sidecar']['image'], self.images[1]['ref'] + '@sha256:' + '2' * 64)
        self.assertTrue(plan['desired']['services']['main']['image'].endswith('@sha256:' + 'a' * 64))
        self.assertEqual(plan['desired']['services']['main']['environment'], {'TOKEN': 'private'})
        self.assertNotIn('private', plan['label'] + plan['effect'])
        self.assertTrue(all(call.args[0] in ('app.config', 'app.get_instance') for call in self.nas.call_args_list))

    def test_multiimage_changes_require_service_selection(self):
        with self.assertRaisesRegex(b.Refused, 'Several images'):
            b.prepare_nas({}, 'app', self.versions)

    def test_local_build_and_configuration_drift_refuse(self):
        for mutation in ['build', 'ref', 'digests']:
            with self.subTest(mutation=mutation):
                original, images = copy.deepcopy(self.original), copy.deepcopy(self.images)
                if mutation == 'build': self.original['services']['main']['build'] = '.'
                if mutation == 'ref': self.images[0]['ref'] = 'other:latest'
                if mutation == 'digests': self.images[0]['digests'] = []
                with self.assertRaises(b.Refused):
                    b.prepare_nas({}, 'app/main', self.versions)
                self.original, self.images = original, images
                self.versions.docker_inventory.return_value = self.images

    def test_major_prerelease_and_downgrade_refuse(self):
        for current, target in [('1.0.0', '2.0.0'), ('1.0.0', '1.1.0-beta1'), ('2.0.0', '1.0.0'), ('0.1.0', '0.2.0'),
                                ('1.0.0', '1.1.0-rc.1'), ('1.0.0', '1.1.0-RC'), ('1.0.0', '1.1.0-preview.1'),
                                ('1.0.0', '1.1.0-rc_1'), ('1.0.0', '1.1.0-pre.1')]:
            with self.subTest(current=current, target=target), self.assertRaises(b.Refused):
                b.same_release_line(current, target)

    def test_stable_image_packaging_suffix_is_allowed(self):
        b.same_release_line('1.0.0-ls1', '1.1.0-ls2')

    def test_config_change_blocks_nas_mutation(self):
        plan = b.prepare_nas({}, 'app/main', self.versions)
        self.original['services']['main']['environment']['TOKEN'] = 'changed'
        self.nas.reset_mock()
        with self.assertRaises(b.Refused):
            b.perform({'platform': 'truenas'}, plan, self.versions, MagicMock())
        self.assertFalse(any(call.args[0] == 'app.update' for call in self.nas.call_args_list))

    def test_exact_image_and_configuration_verified_after_update(self):
        plan = b.prepare_nas({}, 'app/main', self.versions)
        updated = copy.deepcopy(self.images)
        updated[0]['image_id'] = plan['expected']['main']
        for image in updated:
            image['container'] = 'a' * 12
        self.versions.docker_inventory.side_effect = [self.images, updated]
        self.versions.command.side_effect = [json.dumps({'Running': True, 'Health': {'Status': 'healthy'}})] * 2
        self.nas.reset_mock()
        self.nas.side_effect = lambda method, *a, **k: (plan['original'] if self.nas.call_count == 1 else plan['desired']) if method == 'app.config' else {'state': 'RUNNING'}
        result = b.perform({'platform': 'truenas'}, plan, self.versions, MagicMock())
        self.assertIn('Exact images', result)
        mutations = [call for call in self.nas.call_args_list if call.args[0] == 'app.update']
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0].args, ('app.update', 'app', {'custom_compose_config': plan['desired']}))


class Backups(unittest.TestCase):
    def test_stale_failed_or_partial_nas_backup_blocks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'BACKUP_ROOT', Path(directory)), \
                patch.object(b.time, 'time', return_value=1793703600):
            path = Path(directory) / 'last-run.json'
            for receipt in [{'passed': False, 'finished': '2026-11-03T10:00:00+00:00', 'completed': ['system-config', 'app-settings', 'appdata']},
                            {'passed': True, 'finished': '2020-01-01T10:00:00+00:00', 'completed': ['system-config', 'app-settings', 'appdata']},
                            {'passed': True, 'finished': '2026-11-03T10:00:00+00:00', 'completed': ['system-config']}]:
                path.write_text(json.dumps(receipt))
                with self.assertRaises(b.Refused):
                    b.backup_receipt()


if __name__ == '__main__':
    unittest.main()
