"""Owner identity, immutable consent, durable execution, and bounded API use."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'roles/maintenance_briefs/files/maintenance-repairs.py'
SPEC = importlib.util.spec_from_file_location('repairs', SOURCE)
repairs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repairs)
SETTINGS = {'repairs_enabled': True, 'owner_user_id': '11111111111111111',
            'bot_user_id': '22222222222222222', 'channel_id': '33333333333333333',
            'bot_token': 'secret-bot-token', 'openai_api_key': 'secret-api-key',
            'repair_model': 'gpt-6.1-sol', 'repair_daily_call_limit': 2}
MESSAGE = '44444444444444444'


def incident(status='proposed'):
    value = {'id': 'incident-test-1', 'test': True, 'status': status,
             'evidence': {'node': 'test-node', 'job': 'os', 'invocation': 'a' * 32, 'failed': True},
             'created': time.time(), 'expires': time.time() + 1800,
             'owner_user_id': SETTINGS['owner_user_id'], 'channel_id': SETTINGS['channel_id'],
             'selected': {'operation': 'noop', 'vmid': 0, 'app': ''},
             'analysis': {'reason': 'Synthetic approval test.', 'unknowns': 'No real repair is tested.'},
             'repair_model': SETTINGS['repair_model'], 'implementation_hash': 'implementation',
             'proposal_id': MESSAGE, 'approved_by': SETTINGS['owner_user_id']}
    value['plan_hash'] = repairs.fingerprint(value['selected'])
    value['proposal_id_content'] = repairs.proposal(value)
    return value


class Repairs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, name, value in [(repairs, 'ROOT', self.root),
                                    (repairs, 'MAINTENANCE_LOCK', self.root / 'maintenance.lock'),
                                    (repairs, 'implementation', lambda: 'implementation')]:
            context = patch.object(target, name, value)
            context.start()
            self.addCleanup(context.stop)
        self.progress_patch = patch.object(repairs, 'progress')
        self.progress = self.progress_patch.start()
        self.addCleanup(self.progress_patch.stop)

    def stored(self):
        return repairs.briefs.read_json(self.root / 'incident-test-1.json')

    def displayed(self, value):
        return {'content': value['proposal_id_content'], 'author': {'id': SETTINGS['bot_user_id']},
                'channel_id': SETTINGS['channel_id']}

    def test_only_owner_normal_reaction_counts(self):
        for user, expected in [({'id': SETTINGS['owner_user_id']}, True),
                               ({'id': SETTINGS['owner_user_id'], 'bot': True}, False),
                               ({'id': '55555555555555555'}, False)]:
            with patch.object(repairs, 'discord', return_value=[user]) as discord:
                self.assertEqual(repairs.reacted(SETTINGS, MESSAGE, '✅'), expected)
            self.assertIn('type=0&after=11111111111111110&limit=1', discord.call_args.args[2])

    def test_approval_matches_display_and_owner_and_is_durable(self):
        value = incident()
        with patch.object(repairs, 'discord', return_value=self.displayed(value)), \
                patch.object(repairs, 'reacted', side_effect=[True, False]):
            repairs.authorize(SETTINGS, value)
        self.assertEqual(self.stored()['status'], 'approved')
        self.assertEqual(self.stored()['approved_by'], SETTINGS['owner_user_id'])

    def test_missing_approval_or_decline_blocks(self):
        for reactions in [[False], [True, True]]:
            value = incident()
            with patch.object(repairs, 'discord', return_value=self.displayed(value)), \
                    patch.object(repairs, 'reacted', side_effect=reactions):
                repairs.authorize(SETTINGS, value)
            self.assertEqual(value['status'], 'proposed')

    def test_expired_replayed_and_different_owner_are_rejected(self):
        for change in [{'expires': 0}, {'status': 'executed'}, {'owner_user_id': '55555555555555555'}]:
            value = {**incident(), **change}
            with patch.object(repairs, 'discord') as discord, self.assertRaises(ValueError):
                repairs.authorize(SETTINGS, value)
            discord.assert_not_called()

    def test_changed_plan_or_prose_is_rejected_before_discord(self):
        for field, changed in [('selected', {'operation': 'retry_os', 'vmid': 100, 'app': ''}),
                               ('analysis', {'reason': 'changed', 'unknowns': 'changed'})]:
            value = incident()
            value[field] = changed
            with patch.object(repairs, 'discord') as discord, self.assertRaises(ValueError):
                repairs.authorize(SETTINGS, value)
            discord.assert_not_called()

    def test_edited_message_wrong_author_or_channel_is_rejected(self):
        for change in [{'content': 'edited'}, {'author': {'id': '55555555555555555'}}, {'channel_id': '55555555555555555'}]:
            value = incident()
            with patch.object(repairs, 'discord', return_value={**self.displayed(value), **change}), self.assertRaises(ValueError):
                repairs.authorize(SETTINGS, value)

    def test_preflight_rejects_disabled_expired_consumed_wrong_owner_and_channel(self):
        for change in [{'expires': 0}, {'status': 'executed'}, {'approved_by': 'other'}, {'channel_id': 'other'}]:
            with self.assertRaises(ValueError):
                repairs.preflight(SETTINGS, {**incident('approved'), **change})
        with self.assertRaises(ValueError):
            repairs.preflight({**SETTINGS, 'repairs_enabled': False}, incident('approved'))

    def test_code_and_plan_changes_invalidate_approval(self):
        for change in [{'implementation_hash': 'changed'}, {'plan_hash': 'changed'}]:
            with self.assertRaises(ValueError):
                repairs.preflight(SETTINGS, {**incident('approved'), **change})

    def test_test_cannot_execute_real_operation_even_with_matching_hash(self):
        value = incident('approved')
        value['selected'] = {'operation': 'retry_os', 'vmid': 100, 'app': ''}
        value['plan_hash'] = repairs.fingerprint(value['selected'])
        with self.assertRaises(ValueError):
            repairs.preflight(SETTINGS, value)

    def test_stale_report_or_removed_candidate_blocks(self):
        value = {**incident('approved'), 'test': False, 'report_hash': 'original'}
        for report_hash, choices in [('changed', {'x': value['selected']}), ('original', {})]:
            with patch.object(repairs, 'source_state', return_value=({}, report_hash)), \
                    patch.object(repairs, 'candidates', return_value=choices), self.assertRaises(ValueError):
                repairs.preflight(SETTINGS, value)

    def test_report_replaced_during_collection_is_rejected(self):
        value = incident()['evidence']
        current = {**value, 'report_current': True}
        for report, status in [({'invocation_id': 'b' * 32}, {'InvocationID': value['invocation'], 'ActiveState': 'failed'}),
                               ({'invocation_id': value['invocation']}, {'InvocationID': value['invocation'], 'ActiveState': 'activating'})]:
            with patch.object(repairs.briefs, 'collect', return_value=current), \
                    patch.object(repairs.briefs, 'read_json', return_value=report), \
                    patch.object(repairs.briefs, 'unit_status', return_value=status), self.assertRaises(ValueError):
                repairs.source_state(value)

    def test_consumed_before_execution_and_not_replayed(self):
        repairs.save(incident('approved'))
        def perform(value):
            self.assertEqual(self.stored()['status'], 'executing')
            self.assertEqual(self.progress.call_args.args[2], 'executing')
            return {'passed': True, 'summary': 'Test passed.'}
        with patch.object(repairs, 'perform', side_effect=perform) as perform:
            repairs.execute(SETTINGS)
            repairs.execute(SETTINGS)
        perform.assert_called_once()
        self.assertEqual(self.stored()['status'], 'executed')

    def test_executor_preserves_controller_progress_updates(self):
        repairs.save(incident('approved'))
        def perform(value):
            current = self.stored()
            current.update(progress_stage='executing', progress_id='55555555555555555')
            repairs.save(current)
            return {'passed': True, 'summary': 'Test passed.'}
        with patch.object(repairs, 'perform', side_effect=perform):
            repairs.execute(SETTINGS)
        self.assertEqual(self.stored()['progress_id'], '55555555555555555')
        self.assertEqual(self.stored()['progress_stage'], 'executing')

    def test_progress_precedes_model_work_and_finishes_after_error(self):
        value = incident('offered')
        value.update(offer_id=MESSAGE, offer_id_reactions=True, progress_id_content='Started')
        def plan(settings, item):
            self.assertEqual(self.stored()['status'], 'planning')
            self.assertEqual(self.progress.call_args.args[2], 'planning')
            raise ValueError('API unavailable')
        with patch.object(repairs, 'reacted', side_effect=[False, True]), \
                patch.object(repairs, 'plan', side_effect=plan), patch.object(repairs, 'publish'):
            repairs.advance(SETTINGS, value)
        self.assertEqual([call.args[2] for call in self.progress.call_args_list], ['planning', 'closed'])

    def test_approval_acknowledged_before_worker_start(self):
        value = incident()
        value['proposal_id_reactions'] = True
        def start(*args, **kwargs):
            self.assertEqual(self.stored()['status'], 'approved')
            self.assertEqual(self.progress.call_args.args[2], 'approved')
        with patch.object(repairs, 'reacted', side_effect=[False, True, True, False]), \
                patch.object(repairs, 'discord', return_value=self.displayed(value)), \
                patch.object(repairs.subprocess, 'run', side_effect=start) as run:
            repairs.advance(SETTINGS, value)
        run.assert_called_once()

    def test_review_notice_precedes_model_call(self):
        value = incident('executed')
        value.update(result={'summary': 'Test completed.'}, progress_id_content='Running')
        def model(*args):
            self.assertEqual(self.stored()['status'], 'reviewing')
            self.assertEqual(self.progress.call_args.args[2], 'reviewing')
            return {'assessment': 'Passed.', 'next_check': 'No action needed.'}
        with patch.object(repairs, 'model', side_effect=model), patch.object(repairs, 'publish'):
            repairs.advance(SETTINGS, value)
        self.assertEqual([call.args[2] for call in self.progress.call_args_list], ['reviewing', 'closed'])

    def test_interrupted_work_clears_busy_indicator(self):
        value = incident('executing')
        value['progress_id_content'] = 'Working'
        with patch.object(repairs.briefs, 'unit_status', return_value={'ActiveState': 'inactive'}), \
                patch.object(repairs, 'publish'):
            repairs.advance(SETTINGS, value)
        self.assertEqual(value['status'], 'closed')
        self.assertEqual(self.progress.call_args.args[2], 'closed')

    def test_progress_edits_one_message_without_changing_proposal_or_calling_model(self):
        self.progress_patch.stop()
        value = incident()
        value['offer_id'] = '66666666666666666'
        original_proposal = value['proposal_id_content']
        def discord(settings, method, route, payload):
            if method == 'POST':
                self.assertEqual(payload['message_reference']['message_id'], value['offer_id'])
            else:
                self.assertEqual(method, 'PATCH')
                self.assertTrue(route.endswith('/55555555555555555'))
            self.assertEqual(payload['allowed_mentions'], {'parse': []})
            return {'id': '55555555555555555', 'channel_id': SETTINGS['channel_id'], 'content': payload['content']}
        with patch.object(repairs, 'discord', side_effect=discord) as send, patch.object(repairs, 'model') as model:
            for stage in ['planning', 'planning', 'proposed', 'approved', 'executing', 'reviewing', 'closed']:
                repairs.progress(SETTINGS, value, stage)
        self.assertEqual([call.args[1] for call in send.call_args_list], ['POST', *['PATCH'] * 5])
        model.assert_not_called()
        self.assertEqual(value['proposal_id_content'], original_proposal)
        self.assertEqual(value['progress_stage'], 'closed')
        self.assertNotIn('Working', value['progress_id_content'])

    def test_progress_corrects_old_nonce_content(self):
        self.progress_patch.stop()
        value = incident()
        receipt = {'id': '55555555555555555', 'channel_id': SETTINGS['channel_id']}
        def send(settings, method, route, payload):
            return {**receipt, 'content': 'Old stage' if method == 'POST' else payload['content']}
        with patch.object(repairs, 'discord', side_effect=send) as discord:
            repairs.progress(SETTINGS, value, 'reviewing')
        self.assertEqual([call.args[1] for call in discord.call_args_list], ['POST', 'PATCH'])
        self.assertEqual(value['progress_stage'], 'reviewing')

    def test_failed_progress_update_can_retry_without_stopping_work(self):
        self.progress_patch.stop()
        value = incident('executing')
        value.update(progress_id='55555555555555555', progress_stage='approved')
        output = io.StringIO()
        with patch.object(repairs, 'discord', side_effect=OSError('secret-token')), contextlib.redirect_stdout(output):
            repairs.progress(SETTINGS, value, 'executing')
        self.assertEqual(value['progress_stage'], 'approved')
        self.assertNotIn('secret-token', output.getvalue())
        with patch.object(repairs, 'discord', side_effect=lambda s, m, r, p: {
                'id': value['progress_id'], 'channel_id': SETTINGS['channel_id'], 'content': p['content']}):
            repairs.progress(SETTINGS, value, 'executing')
        self.assertEqual(value['progress_stage'], 'executing')

    def test_crash_after_consumption_never_replays(self):
        repairs.save(incident('approved'))
        with patch.object(repairs, 'perform', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                repairs.execute(SETTINGS)
        with patch.object(repairs, 'perform') as perform:
            repairs.execute(SETTINGS)
        perform.assert_not_called()
        self.assertEqual(self.stored()['status'], 'executing')

    def test_failed_preflight_closes_instead_of_retrying(self):
        repairs.save({**incident('approved'), 'expires': 0})
        with patch.object(repairs, 'perform') as perform:
            repairs.execute(SETTINGS)
        perform.assert_not_called()
        self.assertEqual(self.stored()['status'], 'closed')

    def test_busy_maintenance_lock_consumes_without_mutation(self):
        repairs.save(incident('approved'))
        with repairs.MAINTENANCE_LOCK.open('a') as lock:
            repairs.fcntl.flock(lock, repairs.fcntl.LOCK_EX)
            with patch.object(repairs, 'perform') as perform:
                repairs.execute(SETTINGS)
        perform.assert_not_called()
        self.assertFalse(self.stored()['result']['passed'])
        self.assertEqual(self.stored()['status'], 'executed')

    def test_private_error_details_do_not_enter_result(self):
        repairs.save(incident('approved'))
        with patch.object(repairs, 'perform', side_effect=RuntimeError('private-password')):
            repairs.execute(SETTINGS)
        self.assertNotIn('private-password', json.dumps(self.stored()))
        self.assertEqual((self.root / 'incident-test-1.log').stat().st_mode & 0o777, 0o600)

    def test_interrupted_states_close_without_new_calls_or_actions(self):
        for status in ['planning', 'reviewing', 'executing']:
            value = incident(status)
            value['result'] = {'summary': 'Test completed.'}
            with patch.object(repairs.briefs, 'unit_status', return_value={'ActiveState': 'inactive'}), \
                    patch.object(repairs, 'publish'), patch.object(repairs, 'model') as model, \
                    patch.object(repairs.subprocess, 'run') as run:
                repairs.advance(SETTINGS, value)
            self.assertEqual(value['status'], 'closed')
            model.assert_not_called()
            run.assert_not_called()

    def test_noop_never_loads_updater_or_runs_command(self):
        with patch.object(repairs, 'load_module') as load, patch.object(repairs.subprocess, 'run') as run:
            self.assertTrue(repairs.perform(incident())['passed'])
        load.assert_not_called()
        run.assert_not_called()

    def updater_fixture(self, operation):
        value = {**incident(), 'test': False, 'selected': {'operation': operation, 'vmid': 100, 'app': ''}}
        updater = MagicMock()
        updater.api.side_effect = lambda path: [{'vmid': 100, 'name': 'guest', 'status': 'running'}] if path.endswith('/lxc') else {}
        os_updater = MagicMock()
        def update(config, requested):
            self.assertEqual(requested, (100,))
            repairs.atomic(os_updater.REPORT_FILE, {'results': [{'vmid': 100, 'status': 'completed'}]})
            return 0
        os_updater.update_guests.side_effect = update
        return value, updater, os_updater

    def test_os_retry_calls_only_approved_guest_and_preserves_scheduled_report(self):
        value, updater, os_updater = self.updater_fixture('retry_os')
        config_path = self.root / 'config.json'
        repairs.atomic(config_path, {'backup_storage': 'test-pbs'})
        with patch.object(repairs, 'load_module', side_effect=[updater, os_updater]), \
                patch.object(repairs, 'APP_ROOT', self.root), patch.object(repairs, 'OS_CONFIG', config_path), \
                patch.object(repairs, 'source_state', return_value=({'results': [{'vmid': 100, 'name': 'guest', 'status': 'failed'}]}, 'hash')):
            self.assertTrue(repairs.perform(value)['passed'])
        updater.backup.assert_not_called()
        os_updater.update_guests.assert_called_once_with({'backup_storage': 'test-pbs'}, requested=(100,))
        self.assertEqual(os_updater.REPORT_FILE, self.root / 'incident-test-1-os-result.json')

    def test_failed_fresh_backup_prevents_update(self):
        value, updater, os_updater = self.updater_fixture('backup_retry_os')
        updater.backup.side_effect = RuntimeError('backup failed')
        with patch.object(repairs, 'load_module', side_effect=[updater, os_updater]), \
                patch.object(repairs.briefs, 'read_json', return_value={'backup_storage': 'test-pbs'}), \
                patch.object(repairs, 'source_state', return_value=({'results': [{'vmid': 100, 'name': 'guest', 'status': 'failed'}]}, 'hash')), \
                self.assertRaises(RuntimeError):
            repairs.perform(value)
        updater.backup.assert_called_once()
        os_updater.update_guests.assert_not_called()

    def test_changed_guest_identity_prevents_os_retry(self):
        value, updater, os_updater = self.updater_fixture('retry_os')
        with patch.object(repairs, 'load_module', side_effect=[updater, os_updater]), \
                patch.object(repairs.briefs, 'read_json', return_value={}), \
                patch.object(repairs, 'source_state', return_value=({'results': [{'vmid': 100, 'name': 'different', 'status': 'failed'}]}, 'hash')), \
                self.assertRaises(ValueError):
            repairs.perform(value)
        os_updater.update_guests.assert_not_called()

    def test_app_retry_reuses_one_guarded_update(self):
        value, updater, _ = self.updater_fixture('retry_app')
        value['selected']['app'] = 'sonarr'
        updater.app_variables.return_value = {'sonarr_hostname': 'guest'}
        updater.yaml.safe_load.return_value = {'sonarr': {'repository': 'example'}}
        updater.update_one.return_value = {'status': 'updated'}
        (self.root / 'catalog.yml').write_text('catalog')
        with patch.object(repairs, 'load_module', return_value=updater), patch.object(repairs, 'APP_ROOT', self.root), \
                patch.object(repairs.briefs, 'read_json', return_value={}):
            self.assertTrue(repairs.perform(value)['passed'])
        args = updater.update_one.call_args
        self.assertEqual(args.args[0], 'sonarr')
        self.assertEqual(args.args[2]['vmid'], 100)
        self.assertFalse(args.args[5])
        self.assertEqual(args.kwargs, {'retry_failed': True})

    def test_candidates_exclude_unsupported_apps_and_successes(self):
        value = {**incident(), 'test': False}
        report = {'results': [{'vmid': 100, 'status': 'failed', 'app': 'sonarr'},
                              {'vmid': 101, 'status': 'completed', 'app': 'sonarr'},
                              {'vmid': 102, 'status': 'failed', 'app': 'packages'},
                              {'vmid': 103, 'status': 'failed', 'app': 'excluded'},
                              {'vmid': '104; rm', 'status': 'failed', 'app': 'sonarr'}]}
        config = {'skip_vmids': [100], 'roles': ['sonarr', 'excluded'], 'exclude': ['excluded']}
        with patch.object(repairs, 'source_state', return_value=(report, 'hash')), \
                patch.object(repairs.briefs, 'read_json', return_value=config):
            self.assertNotIn('retry_os:100', repairs.candidates(value))
            value['evidence']['job'] = 'apps'
            self.assertEqual(list(repairs.candidates(value)), ['retry_app:100:sonarr'])

    def test_drill_candidates_are_only_the_configured_guest_and_backup_retry(self):
        value = {**incident(), 'test': False}
        value['evidence']['job'] = 'drill'
        report = {'results': [{'vmid': vmid, 'status': 'failed'} for vmid in [114, 999]]}
        config = {'roles': [], 'exclude': [], 'skip_vmids': [], 'drill_vmid': 114}
        with patch.object(repairs, 'source_state', return_value=(report, 'hash')), \
                patch.object(repairs.briefs, 'read_json', return_value=config):
            self.assertEqual(repairs.candidates(value), {'backup_retry_os:114': {'operation': 'backup_retry_os', 'vmid': 114, 'app': ''}})

    def test_drill_guard_rejects_service_guests_mounts_privilege_and_locks(self):
        updater = MagicMock()
        config = {'skip_vmids': [], 'backup_storage': 'test-pbs', 'backup_max_age_hours': 8}
        row = {'vmid': 114, 'name': 'terraform-pilot', 'status': 'running'}
        guest = {'hostname': 'terraform-pilot', 'unprivileged': 1}
        def read(path):
            return {'drill_vmid': 114} if path == repairs.CONFIG else config
        for changes in [{'hostname': 'production'}, {'unprivileged': 0}, {'mp0': 'shared'}, {'dev0': 'device'},
                        {'lock': 'backup'}, {'lxc': ['mount.entry: shared']}]:
            updater.api.side_effect = lambda path: [row] if path.endswith('/lxc') else {**guest, **changes}
            with patch.object(repairs, 'load_module', return_value=updater), \
                    patch.object(repairs.briefs, 'read_json', side_effect=read), self.assertRaises(ValueError):
                repairs.drill_guest()
        updater.api.side_effect = lambda path: [row] if path.endswith('/lxc') else guest
        with patch.object(repairs, 'load_module', return_value=updater), patch.object(repairs.briefs, 'read_json', side_effect=read):
            vmid, _, result = repairs.drill_guest()
        self.assertEqual(vmid, 114)
        self.assertEqual(result['backup_max_age_hours'], 0.25)
        self.assertEqual(config['backup_max_age_hours'], 8)
        updater.update_guests.assert_not_called()

    def test_disabled_drill_refuses_before_guest_access(self):
        with patch.object(repairs.briefs, 'read_json', return_value={'drill_vmid': 0}), \
                patch.object(repairs, 'load_module') as load, self.assertRaises(ValueError):
            repairs.drill_guest()
        load.assert_not_called()

    def test_drill_reports_real_backup_check_without_mutation(self):
        updater = MagicMock()
        updater.api.return_value = []
        report_path = self.root / 'drill-report.json'
        for passed in [False, True]:
            updater.recent_backup.return_value = passed
            with patch.object(repairs, 'drill_guest', return_value=(114, updater, {'backup_storage': 'test-pbs', 'backup_max_age_hours': 0.25})), \
                    patch.dict(repairs.os.environ, {'INVOCATION_ID': 'b' * 32}), \
                    patch.dict(repairs.briefs.JOBS, {'drill': ('maintenance-repair-drill.service', report_path)}), \
                    patch.object(repairs.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(repairs.drill(), int(not passed))
            report = json.loads(report_path.read_text())
            self.assertEqual(report['invocation_id'], 'b' * 32)
            self.assertEqual(report['results'][0]['vmid'], 114)
            self.assertEqual(report['results'][0]['status'], 'completed' if passed else 'failed')
            updater.update_guests.assert_not_called()
            run.assert_not_called()

    def test_drill_requires_systemd_invocation(self):
        with patch.dict(repairs.os.environ, {'INVOCATION_ID': ''}), \
                patch.object(repairs, 'drill_guest') as guest, self.assertRaises(ValueError):
            repairs.drill()
        guest.assert_not_called()

    def test_drill_repair_applies_stricter_backup_guard_only_to_test_target(self):
        value, updater, os_updater = self.updater_fixture('backup_retry_os')
        value['evidence']['job'] = 'drill'
        config_path = self.root / 'config.json'
        repairs.atomic(config_path, {'backup_storage': 'test-pbs', 'backup_max_age_hours': 8})
        strict = {'backup_storage': 'test-pbs', 'backup_max_age_hours': 0.25}
        with patch.object(repairs, 'load_module', side_effect=[updater, os_updater]), \
                patch.object(repairs, 'APP_ROOT', self.root), patch.object(repairs, 'OS_CONFIG', config_path), \
                patch.object(repairs, 'drill_guest', return_value=(100, os_updater, strict)), \
                patch.object(repairs, 'source_state', return_value=({'results': [{'vmid': 100, 'name': 'guest', 'status': 'failed'}]}, 'hash')):
            self.assertTrue(repairs.perform(value)['passed'])
        updater.backup.assert_called_once()
        self.assertEqual(updater.backup.call_args.args[0], 100)
        os_updater.update_guests.assert_called_once_with(strict, requested=(100,))

    def test_model_failures_consume_bounded_budget_and_do_not_retry(self):
        with patch.object(repairs.briefs, 'post', side_effect=RuntimeError('secret')) as post:
            for _ in range(3):
                with self.assertRaises((ValueError, RuntimeError)):
                    repairs.model(SETTINGS, {}, {'field': {'type': 'string'}}, 'Analyze.')
        self.assertEqual(post.call_count, 2)
        payload = post.call_args.args[1]
        self.assertEqual(payload['model'], 'gpt-6.1-sol')
        self.assertEqual(payload['reasoning'], {'effort': 'high'})
        self.assertEqual(payload['max_output_tokens'], 6000)
        self.assertFalse(payload['store'])
        self.assertNotIn('tools', payload)
        self.assertNotIn('secret', payload['input'])

    def test_model_cannot_return_commands_as_executable_candidate(self):
        value = incident('planning')
        with patch.object(repairs, 'model', return_value={'candidate': 'shell:rm', 'reason': 'Invalid', 'unknowns': ''}):
            repairs.plan(SETTINGS, value)
        self.assertEqual(value['status'], 'closed')

    def test_incomplete_model_usage_is_saved_before_validation(self):
        value = incident('planning')
        response = {'status': 'incomplete', 'model': 'gpt-6.1-sol', 'service_tier': 'default',
                    'usage': {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 6000}}
        with patch.object(repairs.briefs, 'post', return_value=response):
            with self.assertRaises(ValueError):
                repairs.model(SETTINGS, {}, {'field': {'type': 'string'}}, 'Analyze.', value)
        self.assertAlmostEqual(self.stored()['plan_usage']['cost_usd'], 0.062)
        value['status'] = 'closed'
        value['outcome'] = 'Analysis unavailable.'
        with patch.object(repairs, 'publish') as publish:
            repairs.advance(SETTINGS, value)
        self.assertIn('Plan: gpt-6.1-sol · ~$0.062000', publish.call_args.args[3])

    def test_discord_scope_checked_before_network(self):
        with patch.object(repairs.urllib.request, 'build_opener') as opener, self.assertRaises(ValueError):
            repairs.discord(SETTINGS, 'GET', '/channels/55555555555555555/messages')
        opener.assert_not_called()

    def test_proposal_delivery_disables_mentions_and_uses_stable_nonce(self):
        value = incident()
        value.pop('proposal_id')
        with patch.object(repairs, 'discord', return_value={'id': MESSAGE, 'channel_id': SETTINGS['channel_id']}) as discord:
            repairs.publish(SETTINGS, value, 'proposal_id', repairs.proposal(value))
            repairs.publish(SETTINGS, value, 'proposal_id', repairs.proposal(value))
        discord.assert_called_once()
        self.assertEqual(discord.call_args.args[3]['allowed_mentions'], {'parse': []})
        self.assertTrue(discord.call_args.args[3]['enforce_nonce'])
        self.assertEqual((self.root / 'incident-test-1.json').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
