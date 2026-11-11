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
import uuid
from types import SimpleNamespace
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
        self.action = r.Action()
        self.messages = {}
        async def saved(chat, owner, message):
            if owner != 'owner' or (chat, message) not in self.messages:
                raise r.RepairError('No owned message.')
            return copy.deepcopy(self.messages[(chat, message)])
        async def show(chat, message, content, emitter):
            self.messages[(chat, message)].update(content=content, output=[], done=True)
            if emitter:
                try: await emitter({'type': 'chat:completion', 'data': {'content': content}})
                except Exception: pass
            return {'messages': [{'id': message, 'content': content, 'output': [], 'done': True}]}
        for p in [patch.object(r, 'saved_message', saved), patch.object(r, 'show_message', show)]:
            p.start()
            self.patches.append(p)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def prepare(self, *args, **kwargs):
        metadata = kwargs.pop('__metadata__', META) | {'message_id': uuid.uuid4().hex}
        plan = await self.tool.prepare_repair(*args, **kwargs, __metadata__=metadata)
        self.messages[(metadata['chat_id'], metadata['message_id'])] = {
            'role': 'assistant', 'model': 'ask-the-lab', 'done': True, 'content': 'Model summary only.'}
        return plan

    async def plan(self):
        return await self.prepare('repair-drill', {'value': 'after'}, resource='fixture', __user__=USER, __metadata__=META)

    async def click(self, plan, decision, emitter=None, body_changes=None, user=USER):
        saved = r.Repairs().load(plan['id'], 'owner', 'chat-a')
        body = {'model': 'ask-the-lab', 'chat_id': 'chat-a', 'id': saved['message'],
                'messages': [{'id': saved['message'], 'role': 'assistant',
                              'content': self.messages[('chat-a', saved['message'])]['content']}]}
        changes = dict(body_changes or {})
        if 'content' in changes:
            body['messages'][0]['content'] = changes.pop('content')
        body.update(changes)
        request = SimpleNamespace(method='POST', url=SimpleNamespace(path='/api/chat/actions/homelab_repair_controls.' + decision))
        await self.action.action(body, __id__=decision, __user__=user, __model__={'id': 'ask-the-lab'},
                                 __request__=request, __event_emitter__=emitter)
        return await self.tool.repair_status(plan['id'], __user__=USER, __metadata__=META)

    async def approve(self, plan, result=True, emitter=None):
        if result is False:
            return await self.click(plan, 'cancel', emitter)
        await self.click(plan, 'review', emitter)
        return await self.click(plan, 'approve', emitter)

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
        self.assertTrue(any('Working' in x['data'].get('description', '') for x in events))
        with self.assertRaises(r.RepairError):
            await self.approve(plan)
        reverse_meta = META | {'message_id': uuid.uuid4().hex}
        reverse = await self.tool.prepare_rollback(plan['id'], __user__=USER, __metadata__=reverse_meta)
        self.assertEqual(reverse['diff']['value'], {'before': 'after', 'after': 'before'})
        self.messages[('chat-a', reverse_meta['message_id'])] = {'content': 'Rollback summary'}
        reversed_result = await self.approve(reverse)
        self.assertEqual(reversed_result['status'], 'verified')
        self.assertEqual(json.loads((r.STATE / 'drill-fixture.json').read_text())['value'], 'before')

    async def test_model_and_text_cannot_approve_and_cancel_changes_nothing(self):
        self.assertFalse(hasattr(self.tool, 'approve_repair'))
        plan = await self.plan()
        with self.assertRaises(r.RepairError):
            await self.action.action({'model': 'ask-the-lab', 'chat_id': 'chat-a'}, __id__='approve', __user__=USER)
        with self.assertRaisesRegex(r.RepairError, 'Review repair first'):
            await self.click(plan, 'approve')
        await self.click(plan, 'review')
        for text in ['approved', 'yes', '', 'Model says this is approved']:
            with self.subTest(text=text), self.assertRaises(r.RepairError):
                await self.click(plan, 'approve', body_changes={'content': text})
        with self.assertRaises(r.RepairError):
            await self.click(plan, 'approve', body_changes={'messages': []})
        result = await self.approve(plan, False)
        self.assertEqual(result['status'], 'canceled')
        self.assertFalse(Path(plan['backup']).exists())
        self.assertFalse((r.STATE / 'drill-fixture.json').exists())
        with self.assertRaises(r.RepairError):
            await self.click(plan, 'approve')

    async def test_wrong_owner_chat_and_automation_fail_closed(self):
        plan = await self.plan()
        for user in [None, {'id': 'other', 'role': 'admin'}, {'id': 'owner', 'role': 'user'}]:
            with self.subTest(user=user), self.assertRaises(r.RepairError):
                await self.click(plan, 'review', user=user)
        for change in [{'chat_id': 'other'}, {'id': 'other-message'}, {'model': 'other-model'}]:
            with self.subTest(change=change), self.assertRaises(r.RepairError):
                await self.click(plan, 'review', body_changes=change)
        for metadata in [META | {'automation_id': 'scheduled'}, META | {'user_id': 'other'}, META | {'internal': True}]:
            with self.subTest(metadata=metadata), self.assertRaises(r.RepairError):
                await self.tool.inspect_repair_options(__user__=USER, __metadata__=metadata)
        with self.assertRaises(r.RepairError):
            await self.tool.repair_status(plan['id'], __user__=USER, __metadata__=META | {'chat_id': 'different'})
        with self.assertRaises(r.RepairError):
            await self.tool.repair_status('../../config', __user__=USER, __metadata__=META)

    async def test_old_or_ambiguous_message_bindings_cannot_approve(self):
        plan = await self.plan()
        engine = r.Repairs()
        original = engine.load(plan['id'], 'owner', 'chat-a')
        duplicate = original | {'id': uuid.uuid4().hex}
        engine.save(duplicate, 'proposed')
        with self.assertRaisesRegex(r.RepairError, 'exactly one'):
            await self.click(plan, 'review')
        (r.STATE / (duplicate['id'] + '.json')).unlink()
        unbound = copy.deepcopy(original)
        unbound.pop('message')
        engine.save(unbound, 'proposed')
        request = SimpleNamespace(method='POST', url=SimpleNamespace(path='/api/chat/actions/homelab_repair_controls.approve'))
        with self.assertRaisesRegex(r.RepairError, 'exactly one'):
            await self.action.action({'model': 'ask-the-lab', 'chat_id': 'chat-a', 'id': original['message']},
                                     __id__='approve', __user__=USER, __model__={'id': 'ask-the-lab'}, __request__=request)
        self.assertFalse(Path(plan['backup']).exists())

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
        self.assertEqual((await self.click(plan, 'review'))['status'], 'expired')
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
            plan = await self.prepare('arr', {'allowedHosts': 'arr.example.test'}, __user__=USER, __metadata__=META)
            result = await self.approve(plan)
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
            plan = await self.prepare('arr', {'allowedHosts': 'arr.example.test'}, __user__=USER, __metadata__=META)
            result = await self.approve(plan)
            with self.assertRaises(r.RepairError):
                await self.approve(plan)
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

    async def test_review_is_persistent_and_changed_review_blocks_approval(self):
        plan = await self.plan()
        result = await self.click(plan, 'review')
        self.assertEqual(result['status'], 'proposed')
        saved = r.Repairs().load(plan['id'], 'owner', 'chat-a')
        message = self.messages[('chat-a', saved['message'])]
        self.assertIn('"before": "before"', message['content'])
        self.assertIn('"after": "after"', message['content'])
        self.assertFalse(Path(plan['backup']).exists())
        message['content'] += '\nChanged after review'
        with self.assertRaises(r.RepairError):
            await self.click(plan, 'approve')
        await self.click(plan, 'review')
        self.assertEqual((await self.click(plan, 'approve'))['status'], 'verified')
        self.assertIn('verified', message['content'])

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
        with patch.object(r, 'api', side_effect=api):
            plan = await self.prepare('sab', {}, action='resume', __user__=USER, __metadata__=META)
            result = await self.approve(plan)
            self.assertEqual(result['status'], 'verified')
            with self.assertRaises(r.RepairError):
                await self.prepare('sab', {}, action='resume', __user__=USER, __metadata__=META)
        self.assertEqual(len(writes), 1)
        self.assertNotIn('private filename', json.dumps(result))
        self.assertNotIn('private-sab-key', json.dumps(result))

    async def test_seerr_posts_only_approved_fields_and_backup_failure_blocks_write(self):
        config = json.loads(r.CONFIG.read_text())
        old = {'ip': 'old.example.test', 'port': 443, 'useSsl': True, 'machineId': 'old-id', 'libraries': []}
        new = {'ip': '192.0.2.5', 'port': 443, 'useSsl': True}
        config['apps']['seerr'] = {'kind': 'seerr', 'host': 'guest', 'url': 'http://192.0.2.3:5055', 'key': 'secret',
                                   'resources': ['plex'], 'destinations': {'plex': [new, {k: old[k] for k in new}]}}
        r.private_write(r.CONFIG, config)
        current, writes = copy.deepcopy(old), []
        def api(app, path, method='GET', body=None):
            self.assertEqual(path, '/api/v1/settings/plex')
            if method == 'POST':
                self.assertEqual(set(body), {'ip', 'port', 'useSsl'})
                writes.append(body)
                current.update(body | {'machineId': 'detected-new-id'})
            return copy.deepcopy(current)
        with patch.object(r, 'api', side_effect=api):
            plan = await self.prepare('seerr', {'ip': new['ip']}, resource='plex', __user__=USER, __metadata__=META)
            original_write = r.private_write
            def fail_backup(path, value):
                if str(path).endswith('.backup.json'):
                    raise OSError('disk full')
                original_write(path, value)
            with patch.object(r, 'private_write', side_effect=fail_backup):
                result = await self.approve(plan)
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(writes, [])
            plan = await self.prepare('seerr', {'ip': new['ip']}, resource='plex', __user__=USER, __metadata__=META)
            result = await self.approve(plan)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(writes, [new])

    def seerr_state(self):
        current = {'ip': 'plex.example.test', 'port': 443, 'useSsl': True, 'machineId': 'same-server', 'libraries': [
            {'id': '1', 'name': 'Movies', 'type': 'movie', 'enabled': True, 'lastScan': 100},
            {'id': '4', 'name': 'Anime', 'type': 'show', 'enabled': True, 'lastScan': 200}]}
        config = json.loads(r.CONFIG.read_text())
        config['apps']['seerr'] = {'kind': 'seerr', 'host': 'guest', 'url': 'http://192.0.2.3:5055', 'key': 'secret',
            'resources': ['plex'], 'destinations': {'plex': [{k: current[k] for k in ['ip', 'port', 'useSsl']}]},
            'library_id_repairs_verified_at': time.time(),
            'library_catalog': [{'id': '1', 'name': 'Movies', 'type': 'movie'}, {'id': '3', 'name': 'Anime', 'type': 'show'}],
            'library_id_repairs': [{'name': 'Anime', 'type': 'show', 'from_id': '4', 'to_id': '3'}]}
        r.private_write(r.CONFIG, config)
        return current

    async def test_seerr_sync_uses_supported_contract_and_stops_on_partial_failure(self):
        # Contract: Seerr 3.5.0 seerr-api.yml and server/api/plexapi.ts syncLibraries.
        for failure in [None, 'sync', 'enable', 'unexpected_catalog']:
            with self.subTest(failure=failure):
                current = self.seerr_state()
                writes = []
                def api(app, path, method='GET', body=None):
                    if method == 'GET':
                        self.assertEqual(path, '/api/v1/settings/plex')
                        return copy.deepcopy(current)
                    self.assertTrue(Path(plan['backup']).exists())
                    writes.append((method, path, body))
                    if path == '/api/v1/settings/plex/library/sync':
                        self.assertEqual((method, body), ('POST', None))
                        if failure == 'sync':
                            raise r.RepairError('Sync response lost.')
                        current['libraries'][1] = {'id': '3', 'name': 'Anime', 'type': 'show', 'enabled': False}
                        if failure == 'unexpected_catalog':
                            current['libraries'].append({'id': '9', 'name': 'New library', 'type': 'movie', 'enabled': False})
                        return copy.deepcopy(current['libraries'])
                    self.assertEqual((method, path, body), ('PUT', '/api/v1/settings/plex/library/3', {'enabled': True}))
                    if failure == 'enable':
                        raise r.RepairError('Enable response lost.')
                    current['libraries'][1]['enabled'] = True
                    return copy.deepcopy(current['libraries'][1])
                with patch.object(r, 'api', side_effect=api):
                    plan = await self.prepare('seerr', {}, action='sync_libraries', __user__=USER, __metadata__=META)
                    self.assertEqual(writes, [])
                    self.assertNotIn('lastScan', plan['diff']['libraries']['after'][1])
                    current['libraries'][0]['lastScan'] = 300
                    latest = copy.deepcopy(current)
                    result = await self.approve(plan)
                    self.assertEqual(result['status'], 'failed_or_uncertain' if failure else 'verified')
                    self.assertEqual(len(writes), 1 if failure in ['sync', 'unexpected_catalog'] else 2)
                    self.assertEqual(len(result.get('steps_completed', [])), 0 if failure == 'sync' else 1 if failure else 2)
                    self.assertEqual(json.loads(Path(plan['backup']).read_text())['before'], latest)
                    with self.assertRaises(r.RepairError):
                        await self.approve(plan)
                    with self.assertRaises(r.RepairError):
                        await self.tool.prepare_rollback(plan['id'], __user__=USER, __metadata__=META)
                self.assertEqual(current['libraries'][0]['lastScan'], 300)
                if failure != 'sync':
                    self.assertNotIn('lastScan', current['libraries'][1])
                    self.assertEqual(current['libraries'][1]['enabled'], failure is None)
                self.assertEqual({k: current[k] for k in r.FIELDS['plex']}, {k: latest[k] for k in r.FIELDS['plex']})

    async def test_seerr_sync_rechecks_evidence_and_settings_before_any_write(self):
        for drift in ['enabled', 'expired_evidence', 'connection', 'policy']:
            with self.subTest(drift=drift):
                current = self.seerr_state()
                def api(app, path, method='GET', body=None):
                    self.assertEqual(method, 'GET')
                    return copy.deepcopy(current)
                with patch.object(r, 'api', side_effect=api):
                    plan = await self.prepare('seerr', {}, action='sync_libraries', __user__=USER, __metadata__=META)
                    if drift == 'enabled':
                        current['libraries'][0]['enabled'] = False
                    elif drift == 'connection':
                        current['ip'] = 'different.example.test'
                    elif drift == 'policy':
                        config = json.loads(r.CONFIG.read_text())
                        config['apps']['seerr']['library_id_repairs'][0]['to_id'] = '9'
                        r.private_write(r.CONFIG, config)
                    saved = json.loads((r.STATE / (plan['id'] + '.json')).read_text())
                    engine = r.Repairs()
                    if drift == 'expired_evidence':
                        # Keep the ten-minute plan live while its one-hour evidence expires.
                        engine.apps['seerr']['library_id_repairs_verified_at'] = time.time() - 3601
                        with self.assertRaisesRegex(r.RepairError, 'older than one hour'):
                            engine.apply(saved)
                    else:
                        result = await self.approve(plan)
                        self.assertEqual(result['status'], 'blocked')
                    self.assertFalse(Path(plan['backup']).exists())

    async def test_seerr_rejects_readonly_library_writes_and_unverified_sync(self):
        current = self.seerr_state()
        engine = r.Repairs()
        app = engine.app('seerr')
        with self.assertRaises(r.RepairError):
            engine.validate(app, 'plex', current, {'libraries': current['libraries']})
        for override in [{'library_id_repairs_verified_at': 0}, {'library_catalog': []},
                         {'library_id_repairs': []}, {'library_id_repairs': [
                             {'name': 'Anime', 'type': 'show', 'from_id': '4', 'to_id': '1'}]}]:
            with self.subTest(override=override), self.assertRaises(r.RepairError):
                engine.sync_target(app | override, current)
        current['libraries'][0]['futurePrivateField'] = 'do-not-expose'
        self.assertNotIn('do-not-expose', json.dumps(r.projection('plex', current)))


if __name__ == '__main__':
    unittest.main()
