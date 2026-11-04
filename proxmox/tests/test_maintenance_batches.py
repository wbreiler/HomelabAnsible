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
    def test_auto_marks_keep_package_architectures_separate(self):
        changes = [{'package': name, 'from': None if name == 'newdep' else '1', 'to': '2'}
                   for name in ['libexample:amd64', 'libexample:i386', 'newdep']]
        plan = {'held': [], 'failed': [], 'packages': changes}
        simulation = '\n'.join('Inst ' + row['package'] + (' [1]' if row['from'] else '') + ' (2 repo)' for row in changes)
        for automatic, expected in [('libexample:i386', ['libexample:i386', 'newdep']),
                                    ('libexample', ['libexample:amd64', 'newdep']), ('', ['newdep'])]:
            with self.subTest(automatic=automatic):
                def read(args):
                    if args == ['dpkg', '--print-architecture']: return 'amd64'
                    if args == ['apt-mark', 'showauto']: return automatic
                    if '--simulate' in args: return simulation
                    return ''
                with patch.object(apt, 'before', return_value={'held': [], 'failed': []}), \
                        patch.object(apt, 'installed', side_effect=[{'libexample:amd64': '1', 'libexample:i386': '1'},
                            {row['package']: '2' for row in changes}]), \
                        patch.object(apt, 'read', side_effect=read) as reads, patch.object(apt.subprocess, 'run'):
                    apt.execute(plan)
                marked = [call.args[0][2:] for call in reads.call_args_list if call.args[0][:2] == ['apt-mark', 'auto']]
                self.assertEqual(marked, [expected])

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
                patch.object(apt, 'read', side_effect=['amd64', '', 'Inst app [1] (2 repo)\nInst other (3 repo)']), \
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
                patch.object(apt, 'read', side_effect=['amd64', 'app', 'Inst app [1] (2 repo)', '']) as read, \
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
        self.assertEqual(q.app_updates.parse('update apps on a'), ('apps', 'a'))
        self.assertEqual(q.app_updates.parse('update os on b'), ('os', 'b'))
        self.assertEqual(q.app_updates.parse('update the homelab'), ('all', '*'))
        self.assertIsNone(q.app_updates.parse('update the homelab; reboot'))
        message = {'channel_id': CHANNEL, 'type': 0, 'author': {'id': OWNER}, 'mentions': [{'id': BOT}],
                   'content': '<@' + BOT + '> check for updates'}
        self.assertEqual(q.intent(message, self.config), 'updates')

    def test_request_scope_reaches_preparation_and_the_visible_plan(self):
        for scope in ('apps', 'os'):
            with self.subTest(scope=scope):
                (Path(self.config['state_dir']) / 'maintenance-batch.json').unlink(missing_ok=True)
                plan = {'scope': scope, 'actions': [], 'notes': []}
                with patch.object(b, 'unit_active', return_value=False), patch.object(b, 'poll_locked'):
                    b.request(q, self.config, {'id': REQUEST}, 'a', scope=scope)
                value = b.read(self.config)
                self.assertEqual(value['nodes'], ['a'])
                self.assertEqual(value['scope'], scope)
                value['local']['phase'] = 'queued'
                b.save(q, self.config, value)
                with patch.object(b.adapters, 'prepare', return_value=plan) as prepare:
                    b.prepare(q, self.config)
                self.assertEqual(prepare.call_args.kwargs['scope'], scope)
                value = b.read(self.config)
                self.assertEqual(value['local']['phase'], 'prepared')
                self.assertIn(b.SCOPES[scope], value['local']['manifest'])
                self.assertIn(b.SCOPES[scope], b.summary(value, {'phase': 'proposed', 'expires': time.time()+60}, {}))

    def test_scope_changes_and_out_of_scope_actions_cannot_execute(self):
        self.value['scope'] = self.value['local']['plan']['scope'] = 'apps'
        self.value['local']['seal'] = b.backend.digest({'plan': self.value['local']['plan'], 'code': 'code',
                    'batch': REQUEST, 'nodes': self.value['nodes'], 'owner': OWNER})
        self.rows = hosts(self.value)
        control = self.approve()
        b.approved(q, self.config, self.value, control)
        for mutation in ('request', 'control', 'plan', 'action', 'os_action'):
            value, changed_control = copy.deepcopy(self.value), copy.deepcopy(control)
            if mutation == 'request': value['scope'] = 'all'
            if mutation == 'control': changed_control['scope'] = 'all'
            if mutation == 'plan': value['local']['plan']['scope'] = 'all'
            if mutation == 'action': value['local']['plan']['actions'][0]['backend'] = 'apt'
            if mutation == 'os_action': value['scope'] = value['local']['plan']['scope'] = changed_control['scope'] = 'os'
            with self.subTest(mutation=mutation), self.assertRaisesRegex(b.backend.Refused, 'scope'):
                b.approved(q, self.config, value, changed_control)

    def test_scoped_request_ignores_other_hosts(self):
        for scope in ('apps', 'os'):
            with self.subTest(scope=scope), patch.object(b, 'unit_active') as active, patch.object(b, 'poll_locked') as poll:
                b.request(q, self.config, {'id': REQUEST}, 'b', scope=scope)
                active.assert_not_called()
                poll.assert_not_called()
                self.assertEqual(b.read(self.config), {})

    def test_mismatched_host_scope_blocks_proposal(self):
        self.rows['b']['scope'] = 'os'
        control = b.coordinate(q, self.config, self.value, self.rows)
        self.assertEqual(control['phase'], 'failed')
        self.assertNotIn('roster', control)

    def test_unsupported_scope_is_explained_in_main_summary(self):
        for platform, scope in [('truenas', 'os'), ('pbs', 'apps')]:
            value = item()
            value.update(nodes=['a'], scope=scope)
            value['local']['plan'] = {'scope': scope, 'actions': [], 'notes': []}
            rows = {'a': hosts(value)['a']}
            control = b.coordinate(q, {**self.config, 'platform': platform}, value, rows)
            self.assertEqual(control['phase'], 'completed')
            self.assertIn(b.adapters.UNSUPPORTED_SCOPES[(platform, scope)], self.display)

    def test_missing_host_prevents_proposal(self):
        control = b.coordinate(q, self.config, self.value, {'a': self.rows['a']})
        self.assertEqual(control['phase'], 'collecting')
        self.assertNotIn('roster', control)

    def test_canceled_summary_does_not_leave_unstarted_hosts_prepared(self):
        self.rows['b']['phase'] = 'executing'
        content = b.summary(self.value, {'phase': 'stopped'}, self.rows)
        self.assertNotIn('prepared', content)
        self.assertIn('not started', content)
        self.assertIn('executing', content)
        content = b.summary(self.value, {'phase': 'stopped', 'approved': time.time()}, self.rows)
        self.assertNotIn('not started', content)
        self.assertIn('last reported: prepared', content)

    def test_failed_cancellation_delivery_retries_before_closing(self):
        config = {**self.config, 'node': 'b'}
        control = {'phase': 'stopped'}
        failed = []
        def publish(q, config, value):
            if value['local']['phase'] == 'stopped' and not failed:
                failed.append(True)
                raise OSError('Temporary Discord failure')
        b.save(q, config, self.value)
        with patch.object(b, 'parent', return_value=True), patch.object(b, 'publish_local', side_effect=publish) as delivery, \
                patch.object(b, 'records', return_value=(self.rows, control)), patch.object(b, 'start') as start:
            with self.assertRaises(OSError):
                b.poll(q, config)
            self.assertEqual(b.read(config)['status'], 'active')
            self.assertEqual(b.read(config)['local']['phase'], 'stopped')
            b.poll(q, config)
            self.assertEqual(b.read(config)['status'], 'closed')
            self.assertGreaterEqual(delivery.call_count, 3)
        start.assert_not_called()

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
    def test_pve_scopes_separate_apps_managed_packages_and_os_actions(self):
        for scope, expected in [('apps', ['managed_packages', 'lxc']), ('os', ['apt', 'apt']),
                                ('all', ['apt', 'managed_packages', 'lxc', 'apt'])]:
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                backend, versions = MagicMock(), MagicMock()
                backend.Refused = b.backend.Refused
                backend.APP_ROOT = root
                updater = backend.load_updater.return_value
                updater.PINS = root
                updater.api.side_effect = lambda path: [{'vmid': 101, 'name': 'app', 'status': 'running'}] if path.endswith('/lxc') else []
                updater.app_variables.return_value = {'app_hostname': 'app'}
                updater.guest.side_effect = lambda vmid, command, *args: '1' if command == 'dpkg-query' else 'managed | 2 | repo'
                updater.apt_candidate.return_value = '2'
                backend.prepare_lxc.return_value = {'backend': 'lxc', 'label': 'app 1 -> 2', 'effect': 'Update app.'}
                settings = {'roles': ['app'], 'packages': ['managed'], 'minimum_age_hours': 1}
                if scope != 'os':
                    (root / 'config.json').write_text(json.dumps(settings))
                (root / 'os.json').write_text(json.dumps({'skip_vmids': []}))
                (root / 'candidate-101-managed.json').write_text(json.dumps({'version': '2', 'first_seen': time.time()-7200}))
                os_plan = {'packages': [{'package': 'base-files', 'from': '1', 'to': '2'}],
                           'held': ['managed'], 'failed': [], 'reboot_required': False}
                with patch.object(b.adapters, 'OS_CONFIG', root / 'os.json'), patch.object(b.adapters, 'apt', return_value=os_plan) as apt:
                    plan = b.adapters.prepare(CONFIG, backend, versions, lambda _: None, scope=scope)
                    self.assertEqual([action['backend'] for action in plan['actions']], expected)
                    self.assertEqual(plan['scope'], scope)
                    self.assertEqual([call.args for call in apt.call_args_list],
                                     [('prepare', 101)] if scope == 'apps' else [('prepare', 101), ('prepare', None)])
                    if scope == 'os':
                        backend.prepare_lxc.assert_not_called()
                        updater.guest.assert_not_called()
                    if scope == 'apps':
                        settings['packages'] = []
                        (root / 'config.json').write_text(json.dumps(settings))
                        apt.reset_mock()
                        plan = b.adapters.prepare(CONFIG, backend, versions, lambda _: None, scope=scope)
                        self.assertEqual([action['backend'] for action in plan['actions']], ['lxc'])
                        apt.assert_not_called()

    def test_unsupported_scopes_do_not_probe_or_update_the_other_scope(self):
        for platform, scope in [('truenas', 'os'), ('pbs', 'apps')]:
            with self.subTest(platform=platform), patch.object(b.adapters, 'apt') as apt:
                backend, versions = MagicMock(), MagicMock()
                plan = b.adapters.prepare({'platform': platform}, backend, versions, lambda _: None, scope=scope)
                self.assertEqual(plan['actions'], [])
                self.assertIn('No updates started', plan['notes'][0])
                self.assertEqual(backend.method_calls, [])
                self.assertEqual(versions.method_calls, [])
                apt.assert_not_called()

    def test_unknown_scope_is_refused_before_any_probe(self):
        backend, versions = MagicMock(), MagicMock()
        with self.assertRaisesRegex(ValueError, 'scope'):
            b.adapters.prepare(CONFIG, backend, versions, lambda _: None, scope='everything')
        self.assertEqual(backend.method_calls, [])
        self.assertEqual(versions.method_calls, [])

    def test_nas_checked_current_image_remains_current(self):
        backend, versions = MagicMock(), MagicMock()
        backend.Refused = b.backend.Refused
        backend.nas_call.return_value = [{'id': 'app', 'custom_app': True, 'state': 'RUNNING'}]
        versions.docker_inventory.return_value = [{'app': 'app', 'service': 'web'}]
        versions.image_updates.return_value = [{'current': '1', 'available': None}]
        result = b.adapters.prepare({'platform': 'truenas'}, backend, versions, lambda _: None)
        self.assertEqual(result['actions'], [])
        self.assertIn('app: current; no eligible changes.', result['notes'])
        backend.prepare_nas.assert_not_called()

    def test_nas_missing_or_unchecked_images_are_not_reported_current(self):
        for state, images, comparisons in [('STOPPED', [], []), ('RUNNING', [], []),
                ('RUNNING', [{'app': 'app', 'service': 'web'}], [{'unavailable': 'Registry timeout'}]),
                ('RUNNING', [{'app': 'app', 'service': 'web'}], [{'manual': True}])]:
            with self.subTest(state=state, comparisons=comparisons):
                backend, versions = MagicMock(), MagicMock()
                backend.Refused = b.backend.Refused
                backend.nas_call.return_value = [{'id': 'app', 'custom_app': True, 'state': state}]
                versions.docker_inventory.return_value = images
                versions.image_updates.return_value = comparisons
                result = b.adapters.prepare({'platform': 'truenas'}, backend, versions, lambda _: None)
                self.assertEqual(result['actions'], [])
                self.assertNotIn('current', ' '.join(result['notes']))
                self.assertTrue(any(note.startswith('app:') and 'excluded' in note for note in result['notes']))
                backend.prepare_nas.assert_not_called()

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
        backend.nas_call.return_value = [{'id': 'app', 'custom_app': True, 'state': 'RUNNING'}]
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
        self.batch_round_trip('all')

    def test_scoped_batches_approve_or_cancel_through_the_same_flow(self):
        for scope in ('apps', 'os'):
            for cancel in (False, True):
                with self.subTest(scope=scope, cancel=cancel):
                    self.batch_round_trip(scope, cancel)

    def batch_round_trip(self, scope, cancel=False):
        with tempfile.TemporaryDirectory() as directory:
            configs = []
            for node in (('a', 'b') if scope == 'all' else ('a',)):
                root = Path(directory) / node
                root.mkdir()
                configs.append({**CONFIG, 'node': node, 'state_dir': str(root), 'platform': 'pve' if scope == 'os' else 'truenas'})
            messages = {CHANNEL: {}}
            sequence = [int(PARENT)]
            green = [False]
            red = [False]
            def discord(config, method='GET', suffix='', payload=None, attachment=None):
                if payload and 'nonce' in payload:
                    self.assertLessEqual(len(str(payload['nonce'])), 25)
                channel = config['channel_id']
                rows = messages.setdefault(channel, {})
                if '/reactions/' in suffix:
                    if method == 'PUT': return None
                    return [{'id': OWNER}] if ('%E2%9C%85' in suffix and green[0]) or ('%E2%9D%8C' in suffix and red[0]) else []
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
            action = {'backend': 'apt' if scope == 'os' else 'truenas', 'label': 'target 1 -> 2', 'effect': 'Service may restart.'}
            if scope == 'os':
                action['apt'] = {'packages': [{'package': 'base-files', 'from': '1', 'to': '2'}]}
            plan = {'scope': scope, 'actions': [action], 'notes': ['Excluded example.']}
            message = {'id': REQUEST, 'content': 'update the homelab' if scope == 'all' else 'update ' + scope + ' on a'}
            with patch.object(q, 'discord', side_effect=discord), patch.object(b, 'implementation', return_value='code'), \
                    patch.object(b, 'unit_active', return_value=False), patch.object(b, 'start') as start, \
                    patch.object(b.adapters, 'prepare', return_value=plan), patch.object(b.adapters, 'perform', return_value='Version verified.') as perform, \
                    patch.object(b, 'Path', side_effect=lambda path: Path(directory) / 'os.lock' if str(path) == '/run/lock/lxc-auto-update.lock' else Path(path)), \
                    patch.object(b.backend, 'BACKUP_ROOT', Path(directory)):
                for config in configs:
                    q.app_updates.request(q, config, message)
                    b.prepare(q, config)
                b.poll(q, configs[-1])
                b.poll(q, configs[0])
                self.assertEqual(b.read(configs[0])['control']['phase'], 'proposed')
                self.assertEqual(b.read(configs[0])['control']['scope'], scope)
                self.assertIn(b.SCOPES[scope], next(iter(messages[CHANNEL].values()))['content'])
                self.assertEqual(len(messages[CHANNEL]), 1)
                perform.assert_not_called()
                if cancel:
                    red[0] = True
                    for config in configs:
                        b.poll(q, config)
                        self.assertEqual(b.read(config)['status'], 'closed')
                    perform.assert_not_called()
                    self.assertIn('Canceled', next(iter(messages[CHANNEL].values()))['content'])
                    return
                green[0] = True
                b.poll(q, configs[0])
                b.poll(q, configs[-1])
                self.assertEqual(b.read(configs[0])['local']['phase'], 'approved')
                if len(configs) > 1:
                    self.assertEqual(b.read(configs[1])['local']['phase'], 'prepared')
                for config in configs:
                    b.poll(q, config)
                    self.assertEqual(b.read(config)['local']['phase'], 'approved')
                    b.execute(q, config)
                    b.poll(q, config)
                    b.poll(q, configs[0])
                self.assertEqual(perform.call_count, len(configs))
                self.assertEqual(b.read(configs[0])['control']['phase'], 'completed')
                self.assertEqual(len(messages[CHANNEL]), 1)
                self.assertIn('Batch finished', next(iter(messages[CHANNEL].values()))['content'])
                self.assertEqual([call.args[0]['node'] for call in perform.call_args_list], [config['node'] for config in configs])


if __name__ == '__main__':
    unittest.main()
