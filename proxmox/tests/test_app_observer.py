import copy
import importlib.util
import json
from pathlib import Path
import socket
import struct
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

SPEC = importlib.util.spec_from_file_location('observer', Path(__file__).resolve().parents[1] / 'files/app-observer/server.py')
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)
TOKEN = 'test-observer-token-never-a-live-secret-0000'


def config():
    return {'token': TOKEN, 'bind': '127.0.0.1', 'clients': ['127.0.0.1'], 'apps': {
        'sonarr': {'kind': 'arr', 'host': 'test-node', 'url': 'http://192.0.2.1:8989', 'key': 'private-app-key'},
        'other': {'kind': 'http', 'host': 'test-node', 'url': 'http://192.0.2.2:8080/health'},
        'unconfigured': {'kind': 'unknown', 'host': 'test-node'},
    }}


class Observations(unittest.TestCase):
    def setUp(self):
        self.app = observer.Observer(config())

    def test_rejects_redirects_without_forwarding_credentials(self):
        request = urllib.request.Request('http://192.0.2.1', headers={'X-Api-Key': 'private'})
        self.assertIsNone(observer.NoRedirect().redirect_request(request, None, 302, '', {}, 'https://example.com'))

    def test_configuration_rejects_public_hosts_and_selector_injection(self):
        for change in [lambda c: c['apps']['other'].update(url='http://example.com/'),
                       lambda c: c['apps']['other'].update(url='http://8.8.8.8/'),
                       lambda c: c['apps']['other'].update(logs=[{'host': 'x"} | json', 'job': 'systemd-journal'}])]:
            cfg = config(); change(cfg)
            with self.assertRaises(ValueError):
                observer.Observer(cfg)

    def test_health_warnings_and_queue_errors_remain_visible_without_private_fields(self):
        responses = [{'version': '1.2', 'appData': '/private/config'},
                     [{'source': 'DownloadClientCheck', 'type': 'warning', 'message': 'Client unavailable', 'wikiUrl': 'https://example.com'}],
                     {'count': 2, 'errors': True, 'title': 'Private media title'}]
        with patch.object(observer, 'read_url', side_effect=responses) as read:
            result = self.app.health('sonarr')
        self.assertEqual(result['status'], 'degraded')
        self.assertTrue(result['checks']['queue']['errors'])
        self.assertNotIn('Private media', json.dumps(result))
        self.assertNotIn('private-app-key', json.dumps(result))
        self.assertEqual([x.args[0].rsplit('/', 1)[-1] for x in read.call_args_list], ['status', 'health', 'status'])

    def test_http_success_is_not_application_health(self):
        with patch.object(observer, 'read_url', return_value=200):
            self.assertEqual(self.app.health('other')['status'], 'responsive')
        self.assertEqual(self.app.health('unconfigured')['status'], 'unknown')
        self.assertEqual(self.app.logs('unconfigured')['coverage'], 'not_collected')

    def test_secret_redaction_and_diagnostic_filter(self):
        cfg = config()
        cfg['apps']['sonarr']['logs'] = [{'host': 'test-node', 'job': 'sonarr'}]
        app = observer.Observer(cfg)
        rows = {'data': {'result': [{'values': [
            ['3', 'ERROR Authorization: Bearer canary123'],
            ['2', 'ERROR connection to https://user:pass@example.com/?apikey=abc failed for me@example.com'],
            ['1', 'ERROR private-app-key rejected'],
            ['1', 'ERROR request to https://example.com/path failed for me@example.com'],
            ['0', 'routine request succeeded'],
        ]}]}}
        with patch.object(observer, 'read_url', return_value=rows):
            result = app.logs('sonarr')
        text = json.dumps(result)
        for secret in ['canary123', 'user:pass', 'apikey=abc', 'me@example.com', 'private-app-key', 'routine request']:
            self.assertNotIn(secret, text)
        self.assertIn('[redacted]', text)
        self.assertIn('[url]', text)
        for bad in ['ERROR password = short', 'ERROR Cookie: id=abc', 'ERROR -----BEGIN PRIVATE KEY-----']:
            self.assertEqual(observer.safe_text(bad), '[sensitive diagnostic withheld]')

    def test_docker_reads_only_state_and_bounded_logs(self):
        cfg = config(); cfg['apps']['plex'] = {'kind': 'docker', 'host': 'nas', 'containers': ['plex']}
        app = observer.Observer(cfg)
        container = {'State': {'Status': 'running', 'Running': True, 'Health': {'Status': 'healthy', 'Log': ['private']}}, 'Config': {'Env': ['PASSWORD=private']}, 'RestartCount': 0}
        with patch.object(observer, 'docker_get', return_value=container) as read, patch.object(app, 'logs', return_value={'entries': []}):
            result = app.health('plex')
        self.assertEqual(result['status'], 'healthy')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(read.call_args.args, ('/containers/plex/json',))
        raw = b'2026-11-10T00:00:00Z ERROR disk read failed\n'
        framed = b'\x01\0\0\0' + struct.pack('>I', len(raw)) + raw
        self.assertEqual(observer.docker_lines(framed), [raw.decode().strip()])
        with self.assertRaises(observer.Unavailable):
            observer.docker_lines(framed[:-1])

    def test_healthy_self_check_keeps_diagnostic_evidence_and_ingestion_time_explicit(self):
        cfg = config(); cfg['apps']['other']['logs'] = [{'host': 'test-node', 'job': 'systemd-journal', 'unit': 'other.service'}]
        app = observer.Observer(cfg)
        rows = {'data': {'result': [{'values': [['1794372051000000000', '2026-11-01 04:00:00 ERROR job failed']]}]}}
        with patch.object(observer, 'read_url', side_effect=[200, rows]):
            result = app.health('other')
        self.assertEqual(result['status'], 'responsive')
        event = result['recent_diagnostics']['entries'][0]
        self.assertEqual(event['time_kind'], 'loki_ingestion')
        self.assertEqual(event['source_time_text'], '2026-11-01 04:00:00')

    def test_unknown_app_and_query_bounds_fail_before_upstream_access(self):
        with patch.object(observer, 'read_url') as read:
            with self.assertRaises(KeyError): self.app.health('http://example.com')
            with self.assertRaises(ValueError): self.app.logs('sonarr', minutes=61)
            with self.assertRaises(ValueError): self.app.logs('sonarr', limit=1000)
        read.assert_not_called()

    def test_one_unavailable_container_does_not_hide_other_diagnostics(self):
        cfg = config(); cfg['apps']['multi'] = {'kind': 'docker', 'host': 'nas', 'containers': ['one', 'two']}
        with patch.object(observer, 'docker_get', side_effect=[b'2026-11-10T00:00:00Z ERROR job failed\n', observer.Unavailable('unavailable')]):
            result = observer.Observer(cfg).logs('multi')
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['unavailable_sources'], ['two'])
        self.assertEqual(len(result['entries']), 1)
        self.assertEqual(observer.select_fields({'status': 'secret-value'}, ['status'], ['secret-value']), {'status': '[redacted]'})

    def test_http_auth_methods_and_fixed_route_boundary(self):
        server = observer.Server(('127.0.0.1', 0), observer.Handler)
        server.observer = self.app
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            def request(path, method='GET', token=TOKEN):
                req = urllib.request.Request(base + path, method=method, headers={'Authorization': 'Bearer ' + token})
                try:
                    with urllib.request.urlopen(req, timeout=3) as response: return response.status, json.load(response)
                except urllib.error.HTTPError as error:
                    with error: return error.code, json.load(error)
            self.assertEqual(request('/apps', token='wrong')[0], 403)
            self.assertEqual(request('/apps', token='wrång')[0], 403)
            self.assertEqual(request('/apps', method='POST')[0], 405)
            self.assertEqual(request('/exec?cmd=id')[0], 404)
            self.assertEqual(request('/logs?app=sonarr&url=http://example.com')[0], 404)
            self.assertEqual(request('/logs?app=sonarr&app=other')[0], 400)
            code, result = request('/openapi.json')
            self.assertEqual(code, 200)
            self.assertEqual(set(result['paths']), {'/apps', '/health', '/logs'})
            self.assertNotIn(TOKEN, json.dumps(result))
            self.assertNotIn('private-app-key', json.dumps(result))
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
