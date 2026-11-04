"""Exact batch plans, one approval, sequential hosts, and interruption boundaries."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'roles/maintenance_queries/files'
spec = importlib.util.spec_from_file_location('batch_queries', ROOT / 'homelab-status.py')
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
b = q.app_updates.batches
apt = b.load('test_approved_apt', ROOT / 'approved_apt.py')
OWNER, BOT, CHANNEL, REQUEST, PARENT = [str(i) * 18 for i in range(1, 6)]
CONFIG = {'node': 'a', 'platform': 'pve', 'query_nodes': ['a', 'b'], 'owner_user_id': OWNER,
          'bot_user_id': BOT, 'channel_id': CHANNEL, 'app_updates_enabled': True}


def item():
    plan = {'actions': [{'backend': 'lxc', 'label': 'app 1 -> 2', 'effect': 'Restart app.'}], 'notes': []}
    value = {'id': REQUEST, 'parent': PARENT, 'owner': OWNER, 'channel': CHANNEL, 'nodes': ['a', 'b'],
             'created': time.time(), 'status': 'active', 'local': {'phase': 'prepared', 'code': 'code',
                 'plan': plan, 'message': '6' * 18, 'stage': 'Ready', 'results': []}}
    value['local']['seal'] = b.backend.digest({'plan': plan, 'code': 'code', 'batch': REQUEST, 'nodes': ['a', 'b'], 'owner': OWNER})
    return value


def hosts(value):
    a = {**b.metadata(value, CONFIG), 'message': value['local']['message']}
    return {'a': a, 'b': {**a, 'node': 'b', 'seal': 'other', 'message': '7' * 18}}


class Apt(unittest.TestCase):
    def test_host_health_requires_every_service(self):
        updater = MagicMock()
        updater.api.side_effect = [[{'type': 'cluster', 'quorate': 1}], []]
        with patch.object(b.backend, 'load_updater', return_value=updater), \
                patch.object(b.adapters.subprocess, 'run') as run:
            b.adapters.host_health(CONFIG, b.backend)
        self.assertEqual([call.args[0][-1] for call in run.call_args_list],
                         ['pveproxy', 'pvedaemon', 'pve-cluster', 'corosync'])
        self.assertTrue(all(call.kwargs['check'] for call in run.call_args_list))
        self.assertEqual(updater.api.call_args.args, ('/nodes/a/tasks', '--source', 'active'))

    def test_multipart_contains_one_text_plan_and_rejects_other_targets(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{}'
        with patch.object(q.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            q.request('https://discord.com/api/v10/channels/' + CHANNEL + '/messages', 'POST',
                      {'attachments': [{'id': 0, 'filename': 'plan.txt'}]}, attachment=('plan.txt', 'app: 1 -> 2'))
            request = opener.return_value.open.call_args.args[0]
            self.assertIn(b'name="payload_json"', request.data)
            self.assertIn(b'name="files[0]"; filename="plan.txt"', request.data)
            self.assertIn(b'app: 1 -> 2', request.data)
            self.assertIn('multipart/form-data', request.headers['Content-type'])
            for url, name in [('https://example.com/upload', 'plan.txt'),
                              ('https://discord.com/api/v10/channels/' + CHANNEL + '/messages', '../plan.txt')]:
                with self.assertRaises(ValueError):
                    q.request(url, attachment=(name, 'plan'))
            self.assertEqual(opener.call_count, 1)

    def test_transaction_includes_exact_new_dependencies(self):
        result = apt.transaction('Inst app [1.0-1] (1.1-1 Debian:stable [amd64])\nInst libnew (2.0 Debian:stable [amd64])\nConf app (1.1-1 Debian [amd64])')
        self.assertEqual(result, [{'package': 'app', 'from': '1.0-1', 'to': '1.1-1'},
                                  {'package': 'libnew', 'from': None, 'to': '2.0'}])

    def test_removals_injection_and_unrecognized_inst_are_rejected(self):
        for text in ['Remv app [1.0]', 'Inst app;reboot [1] (2 origin)', 'Inst app [1] (2;reboot origin)', 'Inst app unexpected']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                apt.transaction(text)

    def test_native_multiarch_lookup_is_unambiguous(self):
        self.assertEqual(apt.lookup({'libc6:amd64': '1.0'}, 'libc6'), '1.0')
        with self.assertRaises(ValueError):
            apt.lookup({'libc6:amd64': '1.0', 'libc6:i386': '1.0'}, 'libc6')

    def test_changed_dependency_or_held_package_blocks_install(self):
        plan = {'held': [], 'failed': [], 'packages': [{'package': 'app', 'from': '1', 'to': '2'}]}
        with patch.object(apt, 'before', return_value={'held': [], 'failed': []}), \
                patch.object(apt, 'installed', return_value={'app': '1'}), \
                patch.object(apt, 'read', side_effect=['', 'Inst app [1] (2 repo)\nInst other (3 repo)']), \
                patch.object(apt.subprocess, 'run') as run, self.assertRaises(ValueError):
            apt.execute(plan)
        run.assert_not_called()
        with patch.object(apt, 'before', return_value={'held': ['app'], 'failed': []}), \
                patch.object(apt.subprocess, 'run') as run, self.assertRaises(ValueError):
            apt.execute(plan)
        run.assert_not_called()

    def test_exact_transaction_preserves_auto_marks_and_no_timeout(self):
        plan = {'held': ['held'], 'failed': [], 'packages': [{'package': 'app', 'from': '1', 'to': '2'}]}
        with patch.object(apt, 'before', return_value={'held': ['held'], 'failed': []}), \
                patch.object(apt, 'installed', side_effect=[{'app': '1'}, {'app': '2'}]), \
                patch.object(apt, 'read', side_effect=['app', 'Inst app [1] (2 repo)', '']) as read, \
                patch.object(apt.subprocess, 'run') as run:
            self.assertEqual(apt.execute(plan)['packages'], 1)
        args = run.call_args
        self.assertIn('--no-remove', args.args[0])
        self.assertIn('app=2', args.args[0])
        self.assertNotIn('--allow-change-held-packages', args.args[0])
        self.assertNotIn('timeout', args.kwargs)
        self.assertEqual(args.kwargs['env']['NEEDRESTART_MODE'], 'l')
        self.assertEqual(read.call_args.args[0], ['apt-mark', 'auto', 'app'])


class Coordination(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {**CONFIG, 'state_dir': self.temp.name}
        self.value = item()
        self.rows = hosts(self.value)
        self.green = False
        self.red = False
        self.display = ''
        self.publish = patch.object(b, 'publish_control', side_effect=self.publish_control).start()
        patch.object(b, 'reacted', side_effect=lambda q,c,i,e: self.green if e == '✅' else self.red).start()
        patch.object(b, 'implementation', return_value='code').start()
        patch.object(q, 'discord', side_effect=self.discord).start()
        self.addCleanup(patch.stopall)

    def discord(self, config, method='GET', suffix='', payload=None, **kwargs):
        return {'id': PARENT, 'channel_id': CHANNEL, 'author': {'id': BOT}, 'content': self.display}

    def publish_control(self, q, config, value, control, rows):
        self.display = b.summary(value, control, rows)
        value['display'] = self.display
        control['display'] = hashlib.sha256(self.display.encode()).hexdigest()
        value['control'] = control

    def approve(self):
        b.coordinate(q, self.config, self.value, self.rows)
        b.coordinate(q, self.config, self.value, self.rows)
        self.green = True
        return b.coordinate(q, self.config, self.value, self.rows)

    def test_batch_commands_keep_read_only_check_separate(self):
        self.assertEqual(q.app_updates.parse('update all on a'), ('all', 'a'))
        self.assertEqual(q.app_updates.parse('update the homelab'), ('all', '*'))
        self.assertIsNone(q.app_updates.parse('update the homelab; reboot'))
        message = {'channel_id': CHANNEL, 'type': 0, 'author': {'id': OWNER}, 'mentions': [{'id': BOT}],
                   'content': '<@' + BOT + '> check for updates'}
        self.assertEqual(q.intent(message, self.config), 'updates')

    def test_missing_host_prevents_proposal(self):
        control = b.coordinate(q, self.config, self.value, {'a': self.rows['a']})
        self.assertEqual(control['phase'], 'collecting')
        self.assertNotIn('roster', control)

    def test_early_reaction_does_not_approve_unseen_plan(self):
        self.green = True
        for _ in range(3):
            control = b.coordinate(q, self.config, self.value, self.rows)
        self.assertEqual(control['phase'], 'proposed')
        self.assertFalse(control['armed'])
        self.green = False
        b.coordinate(q, self.config, self.value, self.rows)
        self.green = True
        self.assertEqual(b.coordinate(q, self.config, self.value, self.rows)['phase'], 'running')

    def test_hosts_run_sequentially_and_failure_stops_remaining(self):
        control = self.approve()
        self.assertEqual(control['active'], 'a')
        self.rows['a']['phase'] = 'executing'
        self.assertEqual(b.coordinate(q, self.config, self.value, self.rows)['active'], 'a')
        self.rows['a']['phase'] = 'failed'
        control = b.coordinate(q, self.config, self.value, self.rows)
        self.assertEqual(control['phase'], 'failed')
        self.assertIsNone(control['active'])

    def test_only_completed_host_releases_next_host(self):
        self.approve()
        self.rows['a']['phase'] = 'completed'
        self.rows['a']['done'] = 1
        self.assertEqual(b.coordinate(q, self.config, self.value, self.rows)['active'], 'b')

    def test_cancellation_stops_pending_actions(self):
        self.approve()
        self.red = True
        control = b.coordinate(q, self.config, self.value, self.rows)
        self.assertEqual(control['phase'], 'stopped')
        self.assertIsNone(control['active'])

    def test_mutated_plan_and_wrong_host_cannot_execute(self):
        control = self.approve()
        b.approved(q, self.config, self.value, control)
        for changed in [{**control, 'active': 'b'}, {**control, 'deadline': 0}]:
            with self.assertRaises(b.backend.Refused):
                b.approved(q, self.config, self.value, changed)
        self.value['local']['plan']['actions'][0]['label'] = 'changed'
        with self.assertRaises(b.backend.Refused):
            b.approved(q, self.config, self.value, control)

    def test_changed_summary_waits_without_executing(self):
        control = self.approve()
        self.display = 'edited while delivering'
        with self.assertRaises(b.AwaitingDisplay):
            b.approved(q, self.config, self.value, control)

    def test_public_manifest_excludes_app_configuration_and_secrets(self):
        self.value['local']['plan']['actions'][0]['original'] = {'TOKEN': 'private-secret'}
        text = b.manifest(self.config, self.value['local']['plan'])
        self.assertIn('app 1 -> 2', text)
        self.assertNotIn('private-secret', text)
        self.assertNotIn('TOKEN', text)

    def test_partial_plan_never_approved_after_timeout(self):
        self.value['created'] = 0
        control = b.coordinate(q, self.config, self.value, {'a': self.rows['a']})
        self.assertEqual(control['phase'], 'failed')

    def test_crash_consumes_batch_before_first_action_and_never_replays(self):
        self.approve()
        self.value['local']['phase'] = 'approved'
        b.save(q, self.config, self.value)
        self.config['platform'] = 'truenas'
        with patch.object(b.backend, 'BACKUP_ROOT', Path(self.temp.name)), \
                patch.object(b, 'records', return_value=(self.rows, self.value['control'])), \
                patch.object(b.adapters, 'perform', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                b.execute(q, self.config)
        stored = b.read(self.config)
        self.assertEqual(stored['local']['phase'], 'executing')
        self.assertEqual(stored['local']['action_started'], 0)
        with patch.object(b.adapters, 'perform') as perform:
            b.execute(q, self.config)
        perform.assert_not_called()


class FleetRoundTrip(unittest.TestCase):
    def test_pve_prepares_three_apps_at_once_in_stable_order(self):
        backend = MagicMock()
        backend.Refused = b.backend.Refused
        updater = backend.load_updater.return_value
        names = ['first', 'second', 'third', 'fourth']
        guests = [{'vmid': i, 'name': app, 'status': 'running'} for i, app in enumerate(names, 100)]
        updater.api.side_effect = lambda path: guests if path.endswith('/lxc') else []
        updater.app_variables.side_effect = lambda app, settings: {app + '_hostname': app}
        barrier = threading.Barrier(3, timeout=5)
        def prepare(config, app):
            if app != 'fourth':
                barrier.wait()
            if app == 'second':
                raise backend.Refused('Unsupported app remains excluded.')
            return {'label': app}
        backend.prepare_lxc.side_effect = prepare
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend.APP_ROOT = updater.PINS = root
            (root / 'config.json').write_text(json.dumps({'roles': names, 'packages': []}))
            (root / 'os.json').write_text(json.dumps({'skip_vmids': []}))
            with patch.object(b.adapters, 'OS_CONFIG', root / 'os.json'), \
                    patch.object(b.adapters, 'apt', return_value={'packages': [], 'held': [], 'reboot_required': False}):
                result = b.adapters.prepare(CONFIG, backend, MagicMock(), lambda _: None)
        self.assertEqual([action['label'] for action in result['actions']], ['first', 'third', 'fourth'])
        self.assertTrue(any('Unsupported app remains excluded' in note for note in result['notes']))
        backend.perform.assert_not_called()

    def test_multiple_nas_images_merge_into_one_redeployment(self):
        backend = MagicMock()
        backend.Refused = b.backend.Refused
        backend.nas_call.return_value = [{'id': 'app', 'custom_app': True}]
        original = {'services': {'first': {'image': 'old1'}, 'second': {'image': 'old2'}}}
        base = {'backend': 'truenas', 'app': 'app', 'original': original,
                'before_images': {'first': 'id1', 'second': 'id2'}, 'effect': 'Redeploy with one new image. Backup exists.'}
        first = {**base, 'service': 'first', 'label': 'first: 1 -> 2',
                 'desired': {'services': {'first': {'image': 'new1'}, 'second': {'image': 'old2@sha256:pinned'}}},
                 'expected': {'first': 'newid1', 'second': 'id2'}}
        second = {**base, 'service': 'second', 'label': 'second: 1 -> 2',
                  'desired': {'services': {'first': {'image': 'old1@sha256:pinned'}, 'second': {'image': 'new2'}}},
                  'expected': {'first': 'id1', 'second': 'newid2'}}
        backend.prepare_nas.side_effect = [first, second]
        versions = MagicMock()
        versions.docker_inventory.return_value = [{'app': 'app', 'service': name} for name in ('first', 'second')]
        versions.image_updates.return_value = [{'available': True}, {'available': True}]
        plan = b.adapters.prepare({'platform': 'truenas'}, backend, versions, lambda _: None)
        self.assertEqual(len(plan['actions']), 1)
        action = plan['actions'][0]
        self.assertEqual(action['desired']['services'], {'first': {'image': 'new1'}, 'second': {'image': 'new2'}})
        self.assertEqual(action['expected'], {'first': 'newid1', 'second': 'newid2'})
        self.assertEqual(action['original'], original)
        self.assertTrue(any('TrueNAS OS' in note and 'excluded' in note for note in plan['notes']))
        versions.docker_inventory.assert_called_once()
        versions.image_updates.assert_called_once()
        versions.image_update.assert_not_called()
        snapshot = backend.prepare_nas.call_args.args[2]
        self.assertEqual(snapshot.docker_inventory(), versions.docker_inventory.return_value)
        self.assertEqual(snapshot.image_update(versions.docker_inventory.return_value[0]), {'available': True})
        backend.perform.assert_not_called()

    def test_one_parent_one_approval_two_sequential_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            configs = []
            for node in ('a', 'b'):
                root = Path(directory) / node
                root.mkdir()
                configs.append({**CONFIG, 'node': node, 'state_dir': str(root), 'platform': 'truenas'})
            messages = {CHANNEL: {}}
            sequence = [int(PARENT)]
            green = [False]
            def discord(config, method='GET', suffix='', payload=None, attachment=None):
                if payload and 'nonce' in payload:
                    self.assertLessEqual(len(str(payload['nonce'])), 25)
                channel = config['channel_id']
                rows = messages.setdefault(channel, {})
                if '/reactions/' in suffix:
                    if method == 'PUT': return None
                    return [{'id': OWNER}] if '%E2%9C%85' in suffix and green[0] else []
                if suffix.endswith('/threads'):
                    message_id = suffix.split('/')[1]
                    rows[message_id]['thread'] = {'id': message_id, 'parent_id': channel, 'type': 11}
                    messages[message_id] = {}
                    return copy.deepcopy(rows[message_id]['thread'])
                if suffix.startswith('?'):
                    return copy.deepcopy(list(rows.values()))
                if method == 'GET':
                    return copy.deepcopy(rows[suffix[1:]])
                if method == 'POST':
                    sequence[0] += 1
                    message_id = str(sequence[0])
                    rows[message_id] = {'id': message_id, 'channel_id': channel, 'author': {'id': BOT}, 'attachments': []}
                else:
                    message_id = suffix[1:]
                row = rows[message_id]
                row.update({key: copy.deepcopy(value) for key, value in payload.items() if key not in ('attachments', 'nonce', 'enforce_nonce')})
                if attachment:
                    retained = [a for a in row['attachments'] if a['id'] in {str(a['id']) for a in payload.get('attachments', [])}]
                    sequence[0] += 1
                    row['attachments'] = retained + [{'id': str(sequence[0]), 'filename': attachment[0], 'size': len(attachment[1])}]
                return copy.deepcopy(row)
            plan = {'actions': [{'backend': 'lxc', 'label': 'app 1 -> 2', 'effect': 'Restart app.'}], 'notes': ['Excluded example.']}
            message = {'id': REQUEST}
            with patch.object(q, 'discord', side_effect=discord), patch.object(b, 'implementation', return_value='code'), \
                    patch.object(b, 'unit_active', return_value=False), patch.object(b, 'start') as start, \
                    patch.object(b.adapters, 'prepare', return_value=plan), patch.object(b.adapters, 'perform', return_value='Version verified.') as perform, \
                    patch.object(b.backend, 'BACKUP_ROOT', Path(directory)):
                for config in configs:
                    b.request(q, config, message, '*')
                    b.prepare(q, config)
                b.poll(q, configs[1])
                b.poll(q, configs[0])
                self.assertEqual(b.read(configs[0])['control']['phase'], 'proposed')
                self.assertEqual(len(messages[CHANNEL]), 1)
                perform.assert_not_called()
                green[0] = True
                b.poll(q, configs[0])
                b.poll(q, configs[1])
                self.assertEqual(b.read(configs[0])['local']['phase'], 'approved')
                self.assertEqual(b.read(configs[1])['local']['phase'], 'prepared')
                b.execute(q, configs[0])
                b.poll(q, configs[0])
                b.poll(q, configs[1])
                self.assertEqual(b.read(configs[1])['local']['phase'], 'approved')
                b.execute(q, configs[1])
                b.poll(q, configs[1])
                b.poll(q, configs[0])
                self.assertEqual(perform.call_count, 2)
                self.assertEqual(b.read(configs[0])['control']['phase'], 'completed')
                self.assertEqual(len(messages[CHANNEL]), 1)
                self.assertIn('Batch finished', next(iter(messages[CHANNEL].values()))['content'])
                self.assertEqual([call.args[0]['node'] for call in perform.call_args_list], ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
