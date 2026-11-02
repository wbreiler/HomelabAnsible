"""Notification freshness, redaction, delivery confirmation, and retry checks."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

SOURCE = Path(__file__).resolve().parents[1] / 'files/lxc-update-notify.py'
SPEC = importlib.util.spec_from_file_location('notify', SOURCE)
notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notify)
URL = 'https://discord.com/api/webhooks/123/example-test-token'


class Notifications(unittest.TestCase):
    def test_current_report_lists_updates_and_failures_without_exception_details(self):
        report = {'invocation_id': 'new', 'results': [
            {'vmid': 100, 'app': 'diun', 'status': 'updated', 'current': '4.33.1'},
            {'vmid': 101, 'app': 'forgejo', 'status': 'failed', 'reason': 'private-credential'},
        ]}
        message = notify.summary('apps', 'exit-code', report, 'new', 'node')
        self.assertIn('Needs attention', message['description'])
        self.assertEqual(message['color'], 0xE74C3C)
        fields = {field['name']: field['value'] for field in message['fields']}
        self.assertIn('**Diun** `4.33.1` · CT 100', fields['Installed versions'])
        self.assertIn('**Forgejo** · CT 101', fields['Failed updates'])
        self.assertIn('journalctl -u lxc-app-updates.service', fields['Next step'])
        self.assertNotIn('private-credential', json.dumps(message))

    def test_old_report_cannot_claim_current_run_success(self):
        report = {'invocation_id': 'old', 'results': [{'vmid': 100, 'app': 'old-app', 'status': 'updated'}]}
        message = notify.summary('apps', 'exit-code', report, 'new', 'node')
        self.assertIn('No report from this run', message['description'])
        self.assertNotIn('old-app', json.dumps(message))
        self.assertNotIn('Installed versions', json.dumps(message))

    def test_os_completion_counts_and_failed_service_result(self):
        report = {'invocation_id': 'new', 'results': [{'vmid': 100, 'status': 'completed'}, {'vmid': 101, 'status': 'skipped'}]}
        message = notify.summary('os', 'success', report, 'new', 'node')
        self.assertEqual({f['name']: f['value'] for f in message['fields']}, {'Completed': '1', 'Failed': '0', 'Skipped': '1'})
        self.assertEqual(message['color'], 0x2ECC71)
        self.assertNotIn('journalctl', json.dumps(message))
        self.assertIn('Needs attention', notify.summary('os', 'timeout', report, 'new', 'node')['description'])

    def test_package_counts_and_readable_versions(self):
        report = {'invocation_id': 'new', 'results': [
            {'vmid': 100, 'app': 'pocket_id', 'status': 'updated', 'current': '2.19.1'},
            {'vmid': 127, 'app': 'packages', 'status': 'updated', 'targets': {'grafana': '13.3.0', 'loki': '3.7.9'}},
        ]}
        message = notify.summary('apps', 'success', report, 'new', 'node')
        fields = {f['name']: f['value'] for f in message['fields']}
        self.assertEqual(fields['Apps updated'], '1')
        self.assertEqual(fields['Packages updated'], '2')
        self.assertIn('**Pocket ID** `2.19.1`', fields['Installed versions'])
        self.assertIn('**Grafana** `13.3.0`', fields['Installed versions'])
        self.assertNotIn('Next step', fields)

    def test_no_updates_is_compact_and_does_not_claim_latest_versions(self):
        report = {'invocation_id': 'new', 'results': [{'vmid': 100, 'app': 'homebridge', 'status': 'current'}]}
        message = notify.summary('apps', 'success', report, 'new', 'node')
        self.assertIn('No eligible updates', message['description'])
        self.assertEqual(message['fields'], [])
        self.assertNotIn('journalctl', json.dumps(message))

    def test_large_reports_preserve_counts_and_actions_within_embed_limits(self):
        for status, result in [('failed', 'exit-code'), ('updated', 'success')]:
            with self.subTest(status=status):
                rows = [{'vmid': i, 'app': 'long_app_' * 40, 'status': status, 'current': '1' * 200} for i in range(500)]
                message = notify.summary('apps', result, {'invocation_id': 'new', 'results': rows}, 'new', 'node')
                fields = {f['name']: f['value'] for f in message['fields']}
                self.assertEqual(fields['Failed' if status == 'failed' else 'Apps updated'], '500')
                self.assertIn('more. See the service log.', json.dumps(fields))
                self.assertIn('journalctl', fields['Next step' if status == 'failed' else 'Full details'])
                self.assertLessEqual(len(message['title']), 256)
                self.assertLessEqual(len(message['description']), 4096)
                self.assertLessEqual(len(message['fields']), 25)
                total = len(message['title']) + len(message['description']) + len(message['author']['name']) + len(message['footer']['text'])
                for field in message['fields']:
                    self.assertLessEqual(len(field['name']), 256)
                    self.assertLessEqual(len(field['value']), 1024)
                    total += len(field['name']) + len(field['value'])
                self.assertLessEqual(total, 6000)

    def test_dynamic_labels_cannot_break_markdown_layout(self):
        report = {'invocation_id': 'new', 'results': [
            {'vmid': 100, 'app': 'odd`name\n**heading**', 'status': 'updated', 'current': '1.2`\n```'},
        ]}
        message = notify.summary('apps', 'success', report, 'new', 'node')
        field = next(f['value'] for f in message['fields'] if f['name'] == 'Installed versions')
        self.assertNotIn('\n', field)
        self.assertNotIn('```', field)

    def test_preview_uses_real_layout_and_clearly_labels_sample_data(self):
        for kind in notify.JOBS:
            with self.subTest(kind=kind), patch('sys.argv', ['notify', kind, '--test']), \
                    patch.object(Path, 'read_text', return_value=json.dumps({'webhook_url': URL})), \
                    patch.object(notify, 'send') as send, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(notify.main(), 0)
                message = send.call_args.args[1]
                self.assertTrue(message['title'].startswith('TEST PREVIEW'))
                self.assertIn('Sample data only. No updates ran.', message['description'])
                self.assertTrue(message['fields'])

    def test_discord_confirms_delivery_and_mentions_are_disabled(self):
        response = io.BytesIO(b'{"id":"123"}')
        response.status = 200
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(notify.urllib.request, 'build_opener', return_value=opener):
            notify.send(URL, {'description': '@everyone test'})
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('?wait=true'))
        self.assertEqual(json.loads(request.data)['allowed_mentions'], {'parse': []})
        self.assertEqual(json.loads(request.data)['embeds'], [{'description': '@everyone test'}])

    def test_invalid_destinations_and_redirects_are_blocked(self):
        for url in ['http://discord.com/api/webhooks/123/token', 'https://evil.example/api/webhooks/123/token', URL + '?redirect=evil']:
            with self.subTest(url=url), patch.object(notify.urllib.request, 'build_opener') as opener, self.assertRaises(ValueError):
                notify.send(url, {'description': 'test'})
            opener.assert_not_called()
        with self.assertRaises(ValueError):
            notify.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.example')

    def test_transient_rate_limit_retries_without_repeating_updates(self):
        response = io.BytesIO(b'{"id":"123"}')
        response.status = 200
        opener = MagicMock()
        opener.open.side_effect = [urllib.error.HTTPError(URL, 429, 'limited', {'Retry-After': '1'}, None), response]
        with patch.object(notify.urllib.request, 'build_opener', return_value=opener), patch.object(notify.time, 'sleep') as sleep:
            notify.send(URL, {'description': 'test'})
        sleep.assert_called_once_with(1)
        self.assertEqual(opener.open.call_count, 2)

    def test_delivery_errors_do_not_log_webhook_credentials(self):
        output = io.StringIO()
        with patch('sys.argv', ['notify', 'os', '--test']), patch.object(Path, 'read_text', return_value=json.dumps({'webhook_url': URL})), \
                patch.object(notify, 'send', side_effect=urllib.error.URLError(URL)), contextlib.redirect_stdout(output):
            self.assertEqual(notify.main(), 1)
        self.assertNotIn('example-test-token', output.getvalue())
        self.assertIn('credentials omitted', output.getvalue())


if __name__ == '__main__':
    unittest.main()
