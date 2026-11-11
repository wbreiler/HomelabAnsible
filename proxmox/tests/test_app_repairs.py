import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('repairs', Path(__file__).resolve().parents[1] / 'files/app-repairs/tool.py')
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)
USER = {'id': 'owner', 'role': 'admin'}
META = {'user_id': 'owner', 'chat_id': 'chat-a', 'session_id': 'live-owner-session'}


class RepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(r, 'CONFIG', root / 'config.json'), patch.object(r, 'STATE', root / 'state')]
        for p in self.patches:
            p.start()
        r.private_write(r.CONFIG, {'owner_id': 'owner', 'apps': {'arr': {
            'kind': 'arr', 'url': 'http://192.0.2.1:8989', 'key': 'private-api-key', 'host': 'guest', 'api_version': 'v3',
            'resources': ['host', 'downloadclient', 'remotepathmapping'],
            'required_hosts': ['arr.example.test'], 'allowed_hosts': ['arr.example.test', 'downloader.example.test'],
            'path_roots': ['/media', '/downloads'],
            'destinations': {'SABnzbd': [{'host': 'downloader.example.test', 'port': 8080, 'useSsl': False, 'urlBase': ''}]}}}})
        self.tool = r.Tools()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def plan(self):
        return await self.tool.prepare_repair('repair-drill', {'value': 'after'}, resource='fixture', __user__=USER, __metadata__=META)

    async def approve(self, plan, result=True, emitter=None):
        async def callback(event):
            self.assertEqual(event['type'], 'confirmation')
            self.assertIn('"before": "before"', event['data']['message'])
            self.assertIn('"after": "after"', event['data']['message'])
            return result
        return await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META,
                                             __event_call__=callback, __event_emitter__=emitter)

    async def test_drill_exact_backup_single_attempt_and_rollback(self):
        plan = await self.plan()
        self.assertFalse((r.STATE / 'drill-fixture.json').exists())
        self.assertNotIn('private-api-key', json.dumps(plan))
        events = []
        async def emit(event):
            events.append(event)
        result = await self.approve(plan, emitter=emit)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(json.loads((r.STATE / 'drill-fixture.json').read_text()), {'value': 'after'})
        self.assertEqual(json.loads(Path(result['backup']).read_text())['before'], {'value': 'before'})
        self.assertEqual(Path(result['backup']).stat().st_mode & 0o777, 0o600)
        self.assertTrue(any('Working' in x['data']['description'] for x in events))
        with self.assertRaises(r.RepairError):
            await self.approve(plan)
        reverse = await self.tool.prepare_rollback(plan['id'], __user__=USER, __metadata__=META)
        self.assertEqual(reverse['diff']['value'], {'before': 'after', 'after': 'before'})
        async def yes(event):
            return True
        reversed_result = await self.tool.approve_repair(reverse['id'], __user__=USER, __metadata__=META, __event_call__=yes)
        self.assertEqual(reversed_result['status'], 'verified')
        self.assertEqual(json.loads((r.STATE / 'drill-fixture.json').read_text())['value'], 'before')

    async def test_false_truthy_disconnect_and_timeout_are_not_approval(self):
        for reply in [False, None, 1, 'yes', {'error': 'disconnected'}, {'approved': True}]:
            with self.subTest(reply=reply):
                plan = await self.plan()
                result = await self.approve(plan, reply)
                self.assertEqual(result['status'], 'canceled')
                self.assertFalse(Path(plan['backup']).exists())
                self.assertFalse((r.STATE / 'drill-fixture.json').exists())

    async def test_no_browser_wrong_owner_chat_and_automation_fail_closed(self):
        plan = await self.plan()
        with self.assertRaises(r.RepairError):
            await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META)
        for user, metadata in [({'id': 'other', 'role': 'admin'}, META),
                               ({'id': 'owner', 'role': 'user'}, META),
                               (USER, META | {'automation_id': 'scheduled'}),
                               (USER, META | {'user_id': 'other'}), (USER, META | {'internal': True})]:
            with self.subTest(user=user, metadata=metadata), self.assertRaises(r.RepairError):
                await self.tool.inspect_repair_options(__user__=user, __metadata__=metadata)
        with self.assertRaises(r.RepairError):
            await self.tool.repair_status(plan['id'], __user__=USER, __metadata__=META | {'chat_id': 'different'})
        with self.assertRaises(r.RepairError):
            await self.tool.repair_status('../../config', __user__=USER, __metadata__=META)

    async def test_stale_state_policy_and_expiry_block_before_write(self):
        plan = await self.plan()
        r.private_write(r.STATE / 'drill-fixture.json', {'value': 'changed-outside'})
        result = await self.approve(plan)
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(Path(plan['backup']).exists())
        (r.STATE / 'drill-fixture.json').unlink()
        plan = await self.plan()
        engine = r.Repairs()
        saved = engine.load(plan['id'], 'owner', 'chat-a')
        saved['expires'] = time.time() - 1
        engine.save(saved, 'proposed')
        with self.assertRaises(r.RepairError):
            await self.approve(plan)
        plan = await self.plan()
        config = json.loads(r.CONFIG.read_text())
        config['policy_version'] = 'changed'
        r.private_write(r.CONFIG, config)
        self.assertEqual((await self.approve(plan))['status'], 'blocked')

    async def test_only_allowlisted_fields_and_exact_destination(self):
        engine = r.Repairs()
        app = engine.app('arr')
        before = {'allowedHosts': '', 'apiKey': 'private-api-key'}
        for changes in [{'apiKey': 'stolen'}, {'allowedHosts': '*'}, {'allowedHosts': 'attacker.test'}, {'allowedHosts': ''}]:
            with self.subTest(changes=changes), self.assertRaises(r.RepairError):
                engine.validate(app, 'host', before, changes)
        self.assertEqual(engine.validate(app, 'host', before, {'allowedHosts': 'arr.example.test'})['allowedHosts']['before'], '')
        client = {'implementation': 'SABnzbd', 'fields': [{'name': k, 'value': v} for k, v in
                  {'host': 'downloader.example.test', 'port': 8080, 'useSsl': False, 'urlBase': None, 'apiKey': 'secret'}.items()]}
        for changes in [{'host': 'attacker.test'}, {'port': 4444}, {'useSsl': 'false'}, {'apiKey': 'changed'}]:
            with self.subTest(changes=changes), self.assertRaises(r.RepairError):
                engine.validate(app, 'downloadclient', client, changes)
        self.assertNotIn('secret', json.dumps(r.projection('downloadclient', client)))
        mapping = {'host': 'downloader.example.test', 'localPath': '/media', 'remotePath': '/downloads'}
        for path in ['/etc', '/media/../etc', '/media-evil']:
            with self.subTest(path=path), self.assertRaises(r.RepairError):
                engine.validate(app, 'remotepathmapping', mapping, {'localPath': path})

    async def test_api_config_write_preserves_all_unedited_fields_and_secrets(self):
        original = {'id': 1, 'allowedHosts': '', 'apiKey': 'private-api-key', 'password': 'password-hash', 'authenticationMethod': 'forms'}
        saved = copy.deepcopy(original)
        writes = []
        def fake_api(app, path, method='GET', body=None):
            if method == 'PUT':
                self.assertEqual(path, '/api/v3/config/host/1')
                writes.append(copy.deepcopy(body))
                saved.update(body)
                return {}
            return copy.deepcopy(saved)
        with patch.object(r, 'api', side_effect=fake_api):
            plan = await self.tool.prepare_repair('arr', {'allowedHosts': 'arr.example.test'}, __user__=USER, __metadata__=META)
            async def yes(event): return True
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(writes, [original | {'allowedHosts': 'arr.example.test'}])
        self.assertNotIn('password-hash', json.dumps(result))
        self.assertNotIn('private-api-key', json.dumps(result))

    async def test_failed_or_ambiguous_write_is_not_retried(self):
        original = {'id': 1, 'allowedHosts': ''}
        writes = []
        def api(app, path, method='GET', body=None):
            if method != 'GET':
                writes.append(path)
                raise r.RepairError('Response lost after request.')
            return original.copy()
        with patch.object(r, 'api', side_effect=api):
            plan = await self.tool.prepare_repair('arr', {'allowedHosts': 'arr.example.test'}, __user__=USER, __metadata__=META)
            async def yes(event): return True
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            with self.assertRaises(r.RepairError):
                await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
        self.assertEqual(result['status'], 'failed_or_uncertain')
        self.assertEqual(len(writes), 1)
        self.assertTrue(Path(plan['backup']).exists())

    async def test_parallel_approval_blocked_and_cancellation_waits_for_write(self):
        plan = await self.plan()
        other = await self.plan()
        started, finish = threading.Event(), threading.Event()
        apply = r.Repairs.apply
        def slow_apply(engine, p):
            started.set()
            finish.wait(timeout=5)
            apply(engine, p)
        with patch.object(r.Repairs, 'apply', slow_apply):
            task = asyncio.create_task(self.approve(plan))
            await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0.01)
            with self.assertRaises(r.RepairError):
                await self.approve(other)
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        result = await self.tool.repair_status(plan['id'], __user__=USER, __metadata__=META)
        self.assertEqual(result['status'], 'verified')

    async def test_event_delivery_failure_does_not_repeat_or_fail_a_write(self):
        plan = await self.plan()
        async def failed(event): raise ConnectionError('gone')
        self.assertEqual((await self.approve(plan, emitter=failed))['status'], 'verified')

    async def test_approval_timeout_closes_progress_without_a_write(self):
        plan = await self.plan()
        events = []
        async def timeout(event): raise TimeoutError()
        async def emit(event): events.append(event)
        with self.assertRaises(TimeoutError):
            await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META,
                                           __event_call__=timeout, __event_emitter__=emit)
        self.assertTrue(events[-1]['data']['done'])
        self.assertEqual((await self.tool.repair_status(plan['id'], __user__=USER, __metadata__=META))['status'], 'canceled')
        self.assertFalse(Path(plan['backup']).exists())

    async def test_sab_resume_requires_paused_queue_and_sends_one_fixed_action(self):
        config = json.loads(r.CONFIG.read_text())
        config['apps']['sab'] = {'kind': 'sabnzbd', 'host': 'storage', 'url': 'http://192.0.2.2:8080',
                                 'key': 'private-sab-key', 'resources': ['queue']}
        r.private_write(r.CONFIG, config)
        paused, writes = True, []
        def api(app, path, method='GET', body=None):
            nonlocal paused
            query = r.urllib.parse.parse_qs(r.urllib.parse.urlsplit(path).query)
            if query['mode'] == ['resume']:
                writes.append(path)
                paused = False
                return {'status': True}
            return {'queue': {'paused': paused, 'slots': [{'filename': 'private filename'}]}}
        async def yes(event): return True
        with patch.object(r, 'api', side_effect=api):
            plan = await self.tool.prepare_repair('sab', {}, action='resume', __user__=USER, __metadata__=META)
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'verified')
            with self.assertRaises(r.RepairError):
                await self.tool.prepare_repair('sab', {}, action='resume', __user__=USER, __metadata__=META)
        self.assertEqual(len(writes), 1)
        self.assertNotIn('private filename', json.dumps(result))
        self.assertNotIn('private-sab-key', json.dumps(result))

    async def test_seerr_posts_only_approved_fields_and_backup_failure_blocks_write(self):
        config = json.loads(r.CONFIG.read_text())
        old = {'ip': 'old.example.test', 'port': 443, 'useSsl': True, 'machineId': 'old-id', 'libraries': []}
        new = {'ip': '192.0.2.5', 'port': 32400, 'useSsl': False}
        config['apps']['seerr'] = {'kind': 'seerr', 'host': 'guest', 'url': 'http://192.0.2.3:5055', 'key': 'secret',
                                   'resources': ['plex'], 'destinations': {'plex': [new, {k: old[k] for k in new}]}}
        r.private_write(r.CONFIG, config)
        current, writes = copy.deepcopy(old), []
        def api(app, path, method='GET', body=None):
            self.assertEqual(path, '/api/v1/settings/plex')
            if method == 'POST':
                writes.append(body)
                current.update(body | {'machineId': 'detected-new-id'})
            return copy.deepcopy(current)
        async def yes(event): return True
        with patch.object(r, 'api', side_effect=api):
            plan = await self.tool.prepare_repair('seerr', new, resource='plex', __user__=USER, __metadata__=META)
            original_write = r.private_write
            def fail_backup(path, value):
                if str(path).endswith('.backup.json'):
                    raise OSError('disk full')
                original_write(path, value)
            with patch.object(r, 'private_write', side_effect=fail_backup):
                result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(writes, [])
            plan = await self.tool.prepare_repair('seerr', new, resource='plex', __user__=USER, __metadata__=META)
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(writes, [new])

    async def test_seerr_library_repair_changes_only_verified_id_with_backup_and_rollback(self):
        old = {'ip': 'plex.example.test', 'port': 443, 'useSsl': True, 'machineId': 'same-server', 'libraries': [
            {'id': '1', 'name': 'Movies', 'type': 'movie', 'enabled': True, 'lastScan': 100},
            {'id': '4', 'name': 'Anime', 'type': 'show', 'enabled': True, 'lastScan': 200}]}
        config = json.loads(r.CONFIG.read_text())
        config['apps']['seerr'] = {'kind': 'seerr', 'host': 'guest', 'url': 'http://192.0.2.3:5055', 'key': 'secret',
            'resources': ['plex'], 'destinations': {'plex': [{k: old[k] for k in ['ip', 'port', 'useSsl']}]},
            'library_id_repairs_verified_at': time.time(),
            'library_id_repairs': [{'name': 'Anime', 'type': 'show', 'from_id': '4', 'to_id': '3'}]}
        r.private_write(r.CONFIG, config)
        new = copy.deepcopy(old['libraries'])
        new[1]['id'] = '3'
        current, writes = copy.deepcopy(old), []
        def api(app, path, method='GET', body=None):
            self.assertEqual(path, '/api/v1/settings/plex')
            if method == 'POST':
                writes.append(copy.deepcopy(body))
                current.update(copy.deepcopy(body))
            return copy.deepcopy(current)
        async def yes(event): return True
        with patch.object(r, 'api', side_effect=api):
            plan = await self.tool.prepare_repair('seerr', {'libraries': new}, resource='plex', __user__=USER, __metadata__=META)
            self.assertEqual(writes, [])
            current['libraries'][0]['lastScan'] = 300
            latest = copy.deepcopy(current)
            applied = copy.deepcopy(new)
            applied[0]['lastScan'] = 300
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(writes, [{'libraries': applied}])
            self.assertEqual(json.loads(Path(plan['backup']).read_text())['before'], latest)
            rollback = await self.tool.prepare_rollback(plan['id'], __user__=USER, __metadata__=META)
            result = await self.tool.approve_repair(rollback['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(current, latest)
            plan = await self.tool.prepare_repair('seerr', {'libraries': applied}, resource='plex', __user__=USER, __metadata__=META)
            current['libraries'][0]['enabled'] = False
            result = await self.tool.approve_repair(plan['id'], __user__=USER, __metadata__=META, __event_call__=yes)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(len(writes), 2)
        engine = r.Repairs()
        app = engine.app('seerr')
        private = copy.deepcopy(old)
        private['libraries'][0]['futurePrivateField'] = 'do-not-expose'
        self.assertNotIn('do-not-expose', json.dumps(r.projection('plex', private)))
        for change in [{'id': '99'}, {'id': '1'}, {'enabled': False}, {'enabled': 1}, {'name': 'Other'}, {'type': 'movie'}, {'lastScan': 999}]:
            bad = copy.deepcopy(new)
            bad[1].update(change)
            with self.subTest(change=change), self.assertRaises(r.RepairError):
                engine.validate(app, 'plex', old, {'libraries': bad})
        for bad in [new[:1], list(reversed(new)), new + [new[0]]]:
            with self.assertRaises(r.RepairError):
                engine.validate(app, 'plex', old, {'libraries': bad})
        with self.assertRaises(r.RepairError):
            engine.validate(app, 'plex', old, {'libraries': new, 'port': 443})
        with self.assertRaises(r.RepairError):
            engine.validate(app | {'library_id_repairs_verified_at': time.time()-3601}, 'plex', old, {'libraries': new})

    async def test_library_evidence_expiring_during_approval_blocks_before_write(self):
        plan = await self.plan()
        calls = 0
        def late_expiry(engine, *args, **kwargs):
            nonlocal calls
            calls += 1
            raise r.RepairError('Evidence expired during approval.')
        with patch.object(r.Repairs, 'validate', late_expiry):
            result = await self.approve(plan)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(calls, 1)
        self.assertFalse(Path(plan['backup']).exists())


if __name__ == '__main__':
    unittest.main()
