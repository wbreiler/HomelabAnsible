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
        self.assertIn('FAILED', message)
        self.assertIn('CT 100 diun 4.33.1', message)
        self.assertIn('CT 101 forgejo', message)
        self.assertNotIn('private-credential', message)

    def test_old_report_cannot_claim_current_run_success(self):
        report = {'invocation_id': 'old', 'results': [{'vmid': 100, 'app': 'old-app', 'status': 'updated'}]}
        message = notify.summary('apps', 'exit-code', report, 'new', 'node')
        self.assertIn('No report from this run', message)
        self.assertNotIn('old-app', message)

    def test_os_completion_counts_and_failed_service_result(self):
        report = {'invocation_id': 'new', 'results': [{'vmid': 100, 'status': 'completed'}, {'vmid': 101, 'status': 'skipped'}]}
        message = notify.summary('os', 'success', report, 'new', 'node')
        self.assertIn('1 guests completed; 0 failed; 1 skipped', message)
        self.assertNotIn('FAILED', message)
        self.assertIn('FAILED', notify.summary('os', 'timeout', report, 'new', 'node'))

    def test_messages_stay_below_discord_limit(self):
        rows = [{'vmid': i, 'app': 'an-application', 'status': 'failed'} for i in range(500)]
        self.assertLessEqual(len(notify.summary('apps', 'exit-code', {'invocation_id': 'new', 'results': rows}, 'new', 'node')), 1900)

    def test_discord_confirms_delivery_and_mentions_are_disabled(self):
        response = io.BytesIO(b'{"id":"123"}')
        response.status = 200
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(notify.urllib.request, 'build_opener', return_value=opener):
            notify.send(URL, '@everyone test')
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.endswith('?wait=true'))
        self.assertEqual(json.loads(request.data)['allowed_mentions'], {'parse': []})

    def test_invalid_destinations_and_redirects_are_blocked(self):
        for url in ['http://discord.com/api/webhooks/123/token', 'https://evil.example/api/webhooks/123/token', URL + '?redirect=evil']:
            with self.subTest(url=url), patch.object(notify.urllib.request, 'build_opener') as opener, self.assertRaises(ValueError):
                notify.send(url, 'test')
            opener.assert_not_called()
        with self.assertRaises(ValueError):
            notify.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.example')

    def test_transient_rate_limit_retries_without_repeating_updates(self):
        response = io.BytesIO(b'{"id":"123"}')
        response.status = 200
        opener = MagicMock()
        opener.open.side_effect = [urllib.error.HTTPError(URL, 429, 'limited', {'Retry-After': '1'}, None), response]
        with patch.object(notify.urllib.request, 'build_opener', return_value=opener), patch.object(notify.time, 'sleep') as sleep:
            notify.send(URL, 'test')
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
