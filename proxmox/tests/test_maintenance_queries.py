"""Owner-only routing, read-only probes, delivery retry, and cost guards."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

SOURCE = Path(__file__).resolve().parents[1] / 'roles/maintenance_queries/files/homelab-status.py'
SPEC = importlib.util.spec_from_file_location('queries', SOURCE)
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)
CONFIG = {'node': 'example', 'platform': 'pve', 'channel_id': '111111111111111111',
          'owner_user_id': '222222222222222222', 'bot_user_id': '333333333333333333',
          'bot_token': 'private-token', 'openai_api_key': 'private-key', 'model': 'gpt-4.1-mini', 'daily_call_limit': 2}
REPORT = {'host': {'updates': 1, 'held_updates': 0}, 'guests': [], 'apps': [], 'limits': ['Not a restore test.']}


def message(text='check for updates', seconds_ago=0):
    return {'id': str((int((time.time()-seconds_ago)*1000)-1420070400000)<<22),
            'channel_id': CONFIG['channel_id'], 'type': 0, 'author': {'id': CONFIG['owner_user_id']},
            'mentions': [{'id': CONFIG['bot_user_id']}], 'content': '<@'+CONFIG['bot_user_id']+'> '+text}


class Routing(unittest.TestCase):
    def test_owner_mentions_recognize_examples(self):
        for text, expected in [('check for updates', 'updates'), ('how is the lab doing?', 'health'),
                               ('what is the health?', 'health'), ('help', 'help')]:
            self.assertEqual(q.intent(message(text), CONFIG), expected)

    def test_nonowner_bots_webhooks_other_channels_and_unmentioned_ignored(self):
        for change in [{'author': {'id': '444444444444444444'}}, {'author': {'id': CONFIG['owner_user_id'], 'bot': True}},
                       {'channel_id': '444444444444444444'}, {'webhook_id': '444444444444444444'},
                       {'mentions': []}, {'type': 7}]:
            self.assertIsNone(q.intent({**message(), **change}, CONFIG))

    def test_mutation_text_cannot_become_a_command(self):
        self.assertEqual(q.intent(message('install updates; rm -rf /'), CONFIG), 'updates')
        self.assertEqual(q.intent(message('restart every service'), CONFIG), 'help')
        with self.assertRaises(ValueError):
            q.collect('rm -rf /', 'pve')

    def test_discord_routes_cannot_escape_configured_channel(self):
        with patch.object(q, 'request') as request:
            with self.assertRaises(ValueError):
                q.discord(CONFIG, suffix='/../../users/@me')
            request.assert_not_called()

    def test_only_fixed_update_reaction_routes_are_accepted(self):
        with patch.object(q, 'request') as request:
            q.discord(CONFIG, 'PUT', '/' + CONFIG['owner_user_id'] + '/reactions/%E2%9C%85/@me')
            q.discord(CONFIG, suffix='/' + CONFIG['owner_user_id'] + '/reactions/%E2%9D%8C?type=0&after=' + CONFIG['owner_user_id'] + '&limit=1')
            self.assertEqual(request.call_count, 2)
            with self.assertRaises(ValueError):
                q.discord(CONFIG, suffix='/' + CONFIG['owner_user_id'] + '/reactions/../../users/@me')

    def test_discord_rate_limit_waits_then_retries_but_openai_does_not(self):
        error = urllib.error.HTTPError('https://discord.com/api/v10/test', 429, 'limited', {}, io.BytesIO(b'{"retry_after":2}'))
        self.addCleanup(error.close)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"ok"}'
        opener = MagicMock()
        opener.open.side_effect = [error, response]
        with patch.object(q.urllib.request, 'build_opener', return_value=opener), patch.object(q.time, 'sleep') as sleep:
            self.assertEqual(q.request('https://discord.com/api/v10/test'), {'id': 'ok'})
        sleep.assert_called_once_with(2.25)
        openai_error = urllib.error.HTTPError('https://api.openai.com/v1/responses', 429, 'limited', {}, io.BytesIO(b'{}'))
        self.addCleanup(openai_error.close)
        opener.open.side_effect = openai_error
        with patch.object(q.urllib.request, 'build_opener', return_value=opener), patch.object(q.time, 'sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                q.request('https://api.openai.com/v1/responses')
        sleep.assert_not_called()


class Probes(unittest.TestCase):
    def setUp(self):
        for name in ['lxc_updates', 'image_updates', 'docker_inventory']:
            mock = patch.object(q.versions, name, return_value=[])
            mock.start()
            self.addCleanup(mock.stop)

    def test_only_allowlisted_probe_fields_leave_host(self):
        value = {'updates': 4, 'held_updates': 1, 'metadata_refreshed': True,
                 'packages': ['secret-package'], 'token': 'private-secret'}
        with patch.object(q, 'run', return_value=json.dumps(value)) as run:
            result = q.probe('updates', 114)
        self.assertEqual(result, {'updates': 4, 'held_updates': 1, 'metadata_refreshed': True})
        self.assertEqual(run.call_args.args[0][:4], ['pct', 'exec', '114', '--'])
        self.assertNotIn('private-secret', json.dumps(result))

    def test_probe_error_and_incomplete_results_are_unknown_not_healthy(self):
        for value in [{}, {'unavailable': 'secret exception'}, {'disk_used_pct': 2, 'memory_used_pct': 4}]:
            with patch.object(q, 'run', return_value=json.dumps(value)):
                result = q.probe('health')
            self.assertEqual(result, {'unavailable': 'Probe unavailable or timed out'})
        with patch.object(q, 'run', side_effect=RuntimeError('private-secret')):
            self.assertNotIn('private-secret', str(q.probe('updates')))

    def test_guest_failure_does_not_hide_other_guest_or_stopped_vm(self):
        guests = [{'vmid': 100, 'name': 'one', 'status': 'running'}, {'vmid': 101, 'name': 'two', 'status': 'running'},
                  {'vmid': 102, 'name': 'three', 'status': 'stopped'}]
        def probe(kind, vmid=None):
            return {'unavailable': 'unavailable'} if vmid == 100 else {'disk_used_pct': 5, 'memory_used_pct': 20, 'failed_units': []}
        with patch.object(q, 'pve', side_effect=[guests, [{'vmid': 122, 'name': 'vm', 'status': 'stopped'}], [{'type': 'cluster', 'quorate': 1}]]), \
                patch.object(q, 'probe', side_effect=probe) as checked, patch.object(q, 'run', return_value='all pools are healthy'):
            result = q.collect('health', 'pve')
        self.assertEqual(len(result['guests']), 4)
        self.assertIn('unavailable', result['guests'][0])
        self.assertEqual(result['guests'][1]['disk_used_pct'], 5)
        self.assertNotIn(('health', 102), [call.args for call in checked.call_args_list])
        self.assertTrue(result['quorate'])

    def test_truenas_selects_metadata_not_secrets_or_app_config(self):
        apps = [{'id': 'custom', 'state': 'RUNNING', 'version': '1.0.0', 'upgrade_available': False,
                 'image_updates_available': False, 'custom_app': True, 'config': {'password': 'secret'}}]
        with patch.object(q, 'midclt', side_effect=[apps, {'code': 'NORMAL', 'status': {'new_version': None}}, 'TrueNAS-test']) as mid:
            result = q.truenas('updates')
        self.assertEqual([call.args[0] for call in mid.call_args_list], ['app.query', 'update.status', 'system.version'])
        self.assertNotIn('secret', json.dumps(result))
        self.assertEqual(result['apps'][0]['app'], 'custom')
        self.assertIn('unavailable', result['apps'][0])
        q.versions.docker_inventory.assert_called_once()
        self.assertIn('cached', result['limits'][0])

    def test_stopped_nas_apps_remain_visible_without_duplicate_running_apps(self):
        apps = [{'id': name, 'state': state, 'version': '1'} for name, state in
                [('stopped', 'STOPPED'), ('running', 'RUNNING')]]
        q.versions.docker_inventory.return_value = [{'app': 'running', 'service': 'web'}]
        q.versions.image_updates.return_value = [{'app': 'running/web', 'current': '1'}]
        with patch.object(q, 'midclt', side_effect=[apps, {'code': 'NORMAL', 'status': {}}, 'TrueNAS-test']):
            result = q.truenas('updates')
        self.assertEqual(len(result['apps']), 2)
        missing = next(row for row in result['apps'] if row['app'] == 'stopped')
        self.assertEqual(missing['state'], 'STOPPED')
        self.assertIn('unavailable', missing)

    def test_truenas_prereleases_and_zfs_cache_are_explicit(self):
        with patch.object(q, 'midclt', side_effect=[[], {'code': 'NORMAL', 'status': {'new_version': {'version': '27.0.0-RC.1'}}}, 'TrueNAS-25.10.7']):
            result = q.truenas('updates')
        self.assertTrue(result['host']['prerelease'])
        self.assertIn('prerelease', q.describe(result['host'], 'updates'))
        self.assertIn('ZFS cache: 60%', q.describe({'memory_used_pct': 80, 'zfs_arc_pct': 60}, 'health'))

    def test_app_inspection_never_uses_deployment_or_candidate_writes(self):
        apps = ['first', 'second', 'third']
        barrier = threading.Barrier(3, timeout=5)
        updater = types.SimpleNamespace()
        updater.yaml = MagicMock()
        updater.yaml.safe_load.return_value = {app: {'package': 'example'} for app in apps}
        updater.app_variables = MagicMock(side_effect=lambda app, config: {app + '_hostname': app})
        updater.current_version = MagicMock(side_effect=lambda *args: (barrier.wait(), '1.0.0')[1])
        updater.guest = MagicMock(return_value='example | 1.0.1 | repo')
        updater.apt_candidate = MagicMock(return_value='1.0.1')
        updater.update_one = MagicMock(side_effect=AssertionError('mutation'))
        updater.package_ready = MagicMock(side_effect=AssertionError('writes pins'))
        updater.backup = MagicMock(side_effect=AssertionError('backup'))
        spec = MagicMock()
        config = {'roles': apps, 'native_guests': {}, 'minimum_age_hours': 72}
        with patch.object(q.Path, 'exists', return_value=True), patch.object(q.Path, 'read_text', return_value=json.dumps(config)), \
                patch.object(q.importlib.util, 'spec_from_file_location', return_value=spec), \
                patch.object(q.importlib.util, 'module_from_spec', return_value=updater):
            rows, limits = q.application_updates([{'vmid': i, 'name': app, 'status': 'running'} for i, app in enumerate(apps, 100)])
        self.assertEqual([row['app'] for row in rows], apps)
        self.assertEqual([row['available'] for row in rows], ['1.0.1'] * 3)
        updater.update_one.assert_not_called()
        updater.package_ready.assert_not_called()
        updater.backup.assert_not_called()


class Workflow(unittest.TestCase):
    def test_inspect_returns_evidence_while_polling_lock_is_held(self):
        config = {**CONFIG, 'state_dir': self.directory.name}
        config_path = Path(self.directory.name) / 'config.json'
        config_path.write_text(json.dumps(config))
        self.path.write_text(json.dumps(self.state))
        with (Path(self.directory.name) / 'lock').open('a') as lock:
            q.fcntl.flock(lock, q.fcntl.LOCK_EX | q.fcntl.LOCK_NB)
            with patch('sys.argv', ['homelab-status', '--config', str(config_path), '--inspect', 'health']), \
                    patch('sys.stdout', new_callable=io.StringIO) as output, \
                    patch.object(q, 'collect', return_value=REPORT), patch.object(q, 'poll_window') as poll:
                q.main()
                self.assertEqual(json.loads(output.getvalue()), REPORT)
        poll.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_cron_polls_every_ten_seconds_and_linux_polls_once(self):
        now = [100.0]
        with patch.object(q.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(q.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + seconds)) as sleep, \
                patch.object(q, 'poll') as poll:
            q.poll_window({**CONFIG, 'platform': 'truenas'}, {}, Path('/unused'))
            self.assertEqual(poll.call_count, 6)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [10] * 5)
            poll.reset_mock(); sleep.reset_mock()
            q.poll_window(CONFIG, {}, Path('/unused'))
            poll.assert_called_once()
            sleep.assert_not_called()

    def test_long_inspection_does_not_extend_cron_poll_window(self):
        now = [100.0]
        with patch.object(q.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(q.time, 'sleep') as sleep, \
                patch.object(q, 'poll', side_effect=lambda *args: now.__setitem__(0, 200)) as poll:
            q.poll_window({**CONFIG, 'platform': 'truenas'}, {}, Path('/unused'))
        poll.assert_called_once()
        sleep.assert_not_called()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'
        self.state = {'day': time.strftime('%Y-%m-%d', time.gmtime()), 'calls': 0, 'checks': 0, 'cursor': '111111111111111111'}

    def test_initial_poll_does_not_execute_historical_messages(self):
        with patch.object(q, 'discord', return_value=[message()]), patch.object(q, 'collect') as collect:
            state = {}
            q.poll(CONFIG, state, self.path)
        collect.assert_not_called()
        self.assertIn('cursor', state)

    def test_stale_mentions_are_ignored(self):
        with patch.object(q, 'discord', return_value=[message(seconds_ago=1000)]), patch.object(q, 'process') as process:
            q.poll(CONFIG, self.state, self.path)
        process.assert_not_called()

    def test_result_delivery_retry_does_not_repeat_check_or_model_call(self):
        self.state['pending'] = {'message_id': message()['id'], 'kind': 'updates'}
        reply = {'id': '555555555555555555', 'channel_id': CONFIG['channel_id']}
        with patch.object(q, 'discord', side_effect=[reply, OSError('failed')]), \
                patch.object(q, 'collect', return_value=REPORT) as collect, patch.object(q, 'summarize', return_value='Measured summary') as model:
            with self.assertRaises(OSError):
                q.process(CONFIG, self.state, self.path)
        persisted = json.loads(self.path.read_text())
        with patch.object(q, 'discord', return_value=reply), patch.object(q, 'collect') as retry, patch.object(q, 'summarize') as retry_model:
            q.process(CONFIG, persisted, self.path)
        collect.assert_called_once()
        model.assert_called_once()
        retry.assert_not_called()
        retry_model.assert_not_called()
        self.assertNotIn('pending', persisted)

    def test_interrupted_inspection_is_not_replayed(self):
        self.state['pending'] = {'message_id': message()['id'], 'reply_id': '555555555555555555', 'kind': 'health', 'started': True}
        with patch.object(q, 'discord', return_value={'id': '555555555555555555'}) as discord, patch.object(q, 'collect') as collect:
            q.process(CONFIG, self.state, self.path)
        collect.assert_not_called()
        self.assertIn('interrupted', discord.call_args.args[3]['content'])

    def test_ai_failure_consumes_attempt_and_falls_back_without_secret(self):
        with patch.object(q, 'request', side_effect=RuntimeError('private-key')) as request:
            for _ in range(3):
                self.assertIn('Measured results', q.summarize(CONFIG, self.state, self.path, REPORT))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(json.loads(self.path.read_text())['calls'], 2)

    def test_ai_has_no_tools_and_uses_normalized_evidence_only(self):
        response = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"summary":"One update."}'}]}]}
        with patch.object(q, 'request', return_value=response) as request:
            self.assertEqual(q.summarize(CONFIG, self.state, self.path, REPORT), 'One update.')
        body = request.call_args.args[2]
        self.assertFalse(body['store'])
        self.assertNotIn('tools', body)
        self.assertNotIn('private-key', body['input'])

    def test_usage_survives_incomplete_summary_and_discord_retry(self):
        response = {'model': 'gpt-4.1-mini-2025-04-14', 'status': 'incomplete', 'service_tier': 'default',
                    'usage': {'input_tokens': 1000, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 300}}
        self.state['pending'] = {'message_id': message()['id'], 'reply_id': '555555555555555555', 'kind': 'updates'}
        with patch.object(q, 'request', return_value=response) as request, patch.object(q, 'collect', return_value=REPORT), \
                patch.object(q, 'discord', side_effect=OSError()):
            with self.assertRaises(OSError):
                q.process(CONFIG, self.state, self.path)
        persisted = json.loads(self.path.read_text())
        self.assertAlmostEqual(persisted['pending']['ai_usage']['cost_usd'], 0.00088)
        self.assertEqual(request.call_args.args[2]['service_tier'], 'default')
        with patch.object(q, 'request') as retry, patch.object(q, 'discord', return_value={'id': '555555555555555555'}) as discord:
            q.process(CONFIG, persisted, self.path)
        retry.assert_not_called()
        self.assertIn('~$0.000880', discord.call_args.args[3]['embeds'][0]['footer']['text'])
        self.assertEqual(persisted['last_result']['ai_usage'], self.state['pending']['ai_usage'])

    def test_budget_skip_costs_zero_and_http_failure_is_unknown(self):
        usage = {}
        self.state['calls'] = 2
        q.summarize(CONFIG, self.state, self.path, REPORT, usage)
        self.assertEqual(usage['cost_usd'], 0)
        self.state['calls'] = 0
        with patch.object(q, 'request', side_effect=OSError()):
            q.summarize(CONFIG, self.state, self.path, REPORT, usage)
        self.assertIsNone(usage['cost_usd'])

    def test_per_minute_and_daily_limits_prevent_more_checks(self):
        for limits in [{'checks': 20}, {'last_checks': {'updates': time.time()}}]:
            state = {**self.state, **limits}
            with patch.object(q, 'discord', return_value=[message()]), patch.object(q, 'process') as process:
                q.poll(CONFIG, state, self.path)
            self.assertTrue('limit reached' in state['pending']['payload']['content'] or 'just ran' in state['pending']['payload']['content'])

    def test_health_then_updates_does_not_hit_same_check_cooldown(self):
        state = {**self.state, 'last_checks': {'health': time.time()}}
        with patch.object(q, 'discord', return_value=[message()]), patch.object(q, 'process'):
            q.poll(CONFIG, state, self.path)
        self.assertNotIn('payload', state['pending'])
        self.assertEqual(state['pending']['kind'], 'updates')
        self.assertEqual(state['checks'], 1)

    def test_long_report_stays_within_discord_embed_limit(self):
        report = {**REPORT, 'guests': [{'vmid': i, 'name': 'guest'*20, 'state': 'running', 'updates': 1} for i in range(200)]}
        value = q.payload(CONFIG, 'updates', report, 's'*1000)
        embed = value['embeds'][0]
        total = len(embed['title']) + len(embed['description']) + len(embed['footer']['text']) + sum(len(f['name'])+len(f['value']) for f in embed['fields'])
        self.assertLessEqual(total, 1000)
        self.assertTrue(all(len(f['value']) <= 1024 for f in embed['fields']))
        self.assertEqual(value['allowed_mentions'], {'parse': []})

    def test_update_reply_prioritizes_confirmed_changes_and_preserves_uncertainty(self):
        report = {**REPORT, 'apps': [
            {'app': 'plex', 'current': 'plexpass', 'latest': 'plexpass sha256:123456789012',
             'available': 'plexpass sha256:123456789012 (image index changed; platform needs review)',
             'comparison_uncertain': True},
            {'app': 'lidarr', 'current': '3.1.0', 'available': '3.1.6'}]}
        embed = q.payload(CONFIG, 'updates', report, 'A long AI summary. '*30)['embeds'][0]
        self.assertLessEqual(len(embed['description']), 200)
        self.assertTrue(embed['description'].endswith('…'))
        lines = embed['fields'][1]['value'].splitlines()
        self.assertTrue(lines[0].startswith('lidarr:'))
        self.assertTrue(lines[1].endswith('(platform unconfirmed)'))


if __name__ == '__main__':
    unittest.main()
