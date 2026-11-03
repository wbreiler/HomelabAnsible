"""Owner identity, immutable consent, durable execution, and bounded API use."""
import importlib.util
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
            return {'passed': True, 'summary': 'Test passed.'}
        with patch.object(repairs, 'perform', side_effect=perform) as perform:
            repairs.execute(SETTINGS)
            repairs.execute(SETTINGS)
        perform.assert_called_once()
        self.assertEqual(self.stored()['status'], 'executed')

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
