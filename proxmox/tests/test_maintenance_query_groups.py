"""One public reply, independent thread results, retry safety, and aggregate costs."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

from test_maintenance_queries import CONFIG, REPORT, message, q


class Discord:
    def __init__(self):
        self.channels = {CONFIG['channel_id']: []}
        self.posts = []
        self.fail_result = False
        self.next_id = int(message()['id']) + 100

    def __call__(self, config, method='GET', suffix='', payload=None):
        channel = config['channel_id']
        rows = self.channels[channel]
        if suffix.endswith('/threads'):
            parent = next(m for m in rows if m['id'] == suffix.split('/')[1])
            thread = {'id': parent['id'], 'parent_id': channel, 'type': 11}
            parent['thread'] = thread
            self.channels.setdefault(thread['id'], [])
            return deepcopy(thread)
        if method == 'POST':
            self.next_id += 1
            result = {**deepcopy(payload), 'id': str(self.next_id), 'channel_id': channel,
                      'author': {'id': CONFIG['bot_user_id']}}
            rows.append(result)
            self.posts.append((channel, result['id']))
            return deepcopy(result)
        if suffix.startswith('?'):
            after = int(suffix.split('&after=')[1]) if '&after=' in suffix else 0
            return deepcopy(list(reversed([m for m in rows if int(m['id']) > after][-100:])))
        result = next(m for m in rows if m['id'] == suffix[1:])
        if method == 'PATCH':
            if self.fail_result and channel != CONFIG['channel_id']:
                self.fail_result = False
                raise OSError('Lost delivery')
            result.update(deepcopy(payload))
        return deepcopy(result)


class Groups(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.nodes = ['first', 'second', 'third', 'fourth']
        self.configs = [{**CONFIG, 'node': node, 'query_nodes': self.nodes} for node in self.nodes]
        self.paths = [Path(self.directory.name) / (node + '.json') for node in self.nodes]
        request_id = message()['id']
        self.states = [{'day': time.strftime('%Y-%m-%d', time.gmtime()), 'calls': 0, 'checks': 1,
                        'cursor': request_id, 'pending': {'message_id': request_id, 'kind': 'updates'}} for _ in self.nodes]
        self.bus = Discord()
        self.addCleanup(patch.stopall)
        patch.object(q, 'discord', side_effect=self.bus).start()
        self.collect = patch.object(q, 'collect', return_value=REPORT).start()
        def summary(config, state, path, report, usage):
            usage.update(attempted=True, model='gpt-4.1-mini-2025-04-14', confirmed=True, cost_usd=0.0001)
            return 'One update is available.'
        self.summary = patch.object(q, 'summarize', side_effect=summary).start()

    def process(self, index):
        q.process(self.configs[index], self.states[index], self.paths[index])

    def refresh(self):
        q.refresh_groups(self.configs[0], self.states[0], self.paths[0])

    def test_four_workers_publish_one_summary_and_four_optional_thread_details(self):
        self.process(1)  # A follower cannot create a competing public message.
        self.collect.assert_not_called()
        self.process(0)
        for i in [2, 3, 1]:
            self.process(i)
        self.refresh()
        public = self.bus.channels[CONFIG['channel_id']]
        self.assertEqual(len(public), 1)
        self.assertEqual(len(self.bus.channels[public[0]['id']]), 4)
        embed = public[0]['embeds'][0]
        self.assertIn('Complete · 4/4', embed['description'])
        self.assertEqual([f['name'] for f in embed['fields']], self.nodes)
        self.assertIn('~$0.000400', embed['footer']['text'])
        self.assertIn('gpt-4.1-mini-2025-04-14', embed['footer']['text'])
        self.assertEqual(public[0]['allowed_mentions'], {'parse': []})
        self.assertEqual(self.summary.call_count, 4)
        self.assertEqual(self.states[0]['bundles'], {})

    def test_delivery_retry_does_not_repeat_inspection_or_api_call(self):
        self.bus.fail_result = True
        with self.assertRaises(OSError):
            self.process(0)
        self.states[0] = json.loads(self.paths[0].read_text())
        self.process(0)
        self.assertEqual(self.collect.call_count, 1)
        self.assertEqual(self.summary.call_count, 1)
        self.assertEqual(len(self.bus.channels[CONFIG['channel_id']]), 1)
        self.assertEqual(len(self.bus.posts), 2)

    def test_existing_parent_is_recovered_without_a_duplicate(self):
        self.process(0)
        previous = self.states[0]['last_result']
        self.states[0]['pending'] = {'message_id': previous['request_id'], 'kind': 'updates', 'started': True}
        self.process(0)
        self.assertEqual(len(self.bus.channels[CONFIG['channel_id']]), 1)
        self.assertEqual(self.collect.call_count, 1)
        details = self.bus.channels[previous['parent_id']][-1]['embeds'][0]
        self.assertIn('interrupted', details['description'])

    def test_unauthenticated_and_webhook_results_do_not_fill_host_sections(self):
        self.process(0)
        parent = self.bus.channels[CONFIG['channel_id']][0]
        thread = self.bus.channels[parent['id']]
        for author, webhook in [('999999999999999999', None), (CONFIG['bot_user_id'], '777777777777777777')]:
            forged = deepcopy(thread[0])
            forged['author']['id'] = author
            forged['webhook_id'] = webhook
            forged['embeds'][0]['title'] = 'second · Updates'
            thread.append(forged)
        self.refresh()
        self.assertIn('1/4', parent['embeds'][0]['description'])
        self.assertIn('Waiting', parent['embeds'][0]['fields'][1]['value'])

    def test_late_hosts_are_explicit_and_completed_results_survive(self):
        self.process(0)
        self.refresh()
        parent = self.bus.channels[CONFIG['channel_id']][0]
        bundle = self.states[0]['bundles'][parent['id']]
        bundle['created'] = time.time() - 1201
        self.bus.channels[parent['id']] = []  # A later page need not contain the earlier terminal result.
        self.refresh()
        self.assertIn('Partial result', parent['embeds'][0]['description'])
        self.assertIn('One update', parent['embeds'][0]['fields'][0]['value'])
        self.assertIn('20 minutes', parent['embeds'][0]['fields'][1]['value'])
        self.assertEqual(self.states[0]['bundles'], {})

    def test_waiting_for_offline_coordinator_does_not_block_new_requests_forever(self):
        self.states[1]['pending']['message_id'] = message(seconds_ago=1201)['id']
        self.process(1)
        self.assertNotIn('pending', self.states[1])
        self.collect.assert_not_called()

    def test_pending_follower_does_not_consume_the_next_request(self):
        cursor = self.states[1]['cursor']
        q.poll(self.configs[1], self.states[1], self.paths[1])
        self.assertEqual(self.states[1]['cursor'], cursor)
        self.assertIn('pending', self.states[1])
        self.collect.assert_not_called()

    def test_only_coordinator_answers_help(self):
        request = message('help')
        self.bus.channels[CONFIG['channel_id']].append(request)
        for index in [1, 2, 3, 0]:
            state = {k: v for k, v in self.states[index].items() if k != 'pending'}
            state['cursor'] = '111111111111111111'
            q.poll(self.configs[index], state, self.paths[index])
        self.assertEqual(len(self.bus.posts), 1)
        self.assertIn('One summary', self.bus.channels[CONFIG['channel_id']][-1]['content'])
        self.collect.assert_not_called()

    def test_group_bounds_and_unknown_cost_are_preserved(self):
        config = {**self.configs[0], 'query_nodes': ['node'+str(i) for i in range(6)]}
        results = {n: {'description': 'x'*450, 'fields': [{'name': 'Measured', 'value': 'x'*500},
                   {'name': 'App versions', 'value': 'x'*1000}], 'footer': {'text': 'gpt-4.1-mini · cost unavailable'}} for n in config['query_nodes']}
        embed = q.group_payload(config, {'kind': 'updates', 'created': time.time()}, results)['embeds'][0]
        size = len(embed['title']) + len(embed['description']) + len(embed['footer']['text'])
        size += sum(len(f['name']) + len(f['value']) for f in embed['fields'])
        self.assertLessEqual(size, 6000)
        self.assertIn('6 host cost unavailable', embed['footer']['text'])
        self.assertTrue(embed['footer']['text'].startswith('Known subtotal'))

    def test_deleted_parent_clears_pending_without_replaying_inspection(self):
        self.process(0)
        self.states[1]['pending']['parent_id'] = self.states[0]['last_result']['parent_id']
        error = urllib.error.HTTPError('https://discord.com', 404, 'Not Found', {}, io.BytesIO(b'{}'))
        self.addCleanup(error.close)
        with patch.object(q, 'discord', side_effect=error):
            self.process(1)
        self.assertNotIn('pending', self.states[1])
        self.assertTrue(self.states[1]['last_result']['delivery_failed'])
        self.assertEqual(self.collect.call_count, 1)

    def test_legacy_footer_is_not_mistaken_for_a_model_or_free_call(self):
        config = {**self.configs[0], 'query_nodes': ['first']}
        results = {'first': {'description': 'Saved check.', 'footer': {'text': 'Read-only; major changes may be included.'}}}
        footer = q.group_payload(config, {'kind': 'updates', 'created': time.time()}, results)['embeds'][0]['footer']['text']
        self.assertIn('1 host cost unavailable', footer)
        self.assertIn('Model unavailable', footer)
        self.assertNotIn('Read-only', footer)

    def test_newest_result_wins_even_when_discord_returns_newest_first(self):
        self.process(0)
        parent = self.bus.channels[CONFIG['channel_id']][0]
        thread = self.bus.channels[parent['id']]
        newer = deepcopy(thread[0])
        newer['id'] = str(int(newer['id']) + 100)
        newer['embeds'][0]['description'] = 'Newer terminal result.'
        thread.append(newer)
        self.refresh()
        self.assertIn('Newer terminal result', parent['embeds'][0]['fields'][0]['value'])
        thread.pop()
        self.refresh()
        self.assertIn('Newer terminal result', parent['embeds'][0]['fields'][0]['value'])


if __name__ == '__main__':
    unittest.main()
