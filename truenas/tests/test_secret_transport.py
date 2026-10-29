"""Check protected API transport and configuration backup publication."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import jinja2
import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_script(path):
    spec = importlib.util.spec_from_file_location('tested_script', ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args == ('system.general.config',):
            return {'ui_port': 85}
        if args[0] == 'core.download':
            return (1, '/download?token=dummy-token')


class SecretTransportTests(unittest.TestCase):
    def setUp(self):
        FakeClient.calls = []
        self.client = patch.dict(sys.modules, {'truenas_api_client': types.SimpleNamespace(Client=FakeClient)})
        self.client.start()
        self.addCleanup(self.client.stop)

    def task(self, path, name):
        tasks = yaml.safe_load((ROOT / path).read_text())
        return next(task for task in tasks if task['name'].startswith(name))

    def run_task(self, task, variables):
        command = task['ansible.builtin.command']
        self.assertTrue(task['no_log'])
        self.assertEqual(command['argv'][:2], ['/usr/bin/python3', '-c'])
        code = command['argv'][2]
        self.assertNotIn('dummy-password', code)
        env = jinja2.Environment()
        env.filters['to_json'] = json.dumps
        env.filters['combine'] = lambda value, extra: {**value, **extra}
        env.filters['dict2items'] = lambda value: [{'key': key, 'value': item} for key, item in value.items()]
        env.filters['items2dict'] = lambda value: {item['key']: item['value'] for item in value}
        stdin = env.from_string(command['stdin']).render(**variables)
        self.assertIn('dummy-password', stdin)
        with patch('sys.stdin', io.StringIO(stdin)):
            exec(compile(code, '<task>', 'exec'), {})

    def test_user_and_application_payloads_use_stdin(self):
        user = {'username': 'example', 'group': 1, 'groups': []}
        variables = {'truenas_entities_user_payload': user,
                     'vault_truenas_user_passwords': {'example': 'dummy-password'},
                     'desired_user': {'username': 'example'}}
        self.run_task(self.task('roles/truenas_entities/tasks/user.yml', 'Create user'), variables)
        self.assertEqual(FakeClient.calls.pop(), (('user.create', dict(user, password='dummy-password')), {}))
        variables['truenas_entities_user_payload'] = dict(user, password='dummy-password')
        variables['truenas_entities_current_user'] = {'id': 2}
        self.run_task(self.task('roles/truenas_entities/tasks/user.yml', 'Update user'), variables)
        self.assertEqual(FakeClient.calls.pop(), (('user.update', 2,
                                                  {'group': 1, 'groups': [], 'password': 'dummy-password'}), {}))

        task = self.task('roles/truenas_config/tasks/singleton.yml', 'Update ')
        self.run_task(task, {'singleton': {'update_method': 'mail.update',
                                           'desired': {'password': 'dummy-password'}}})
        self.assertEqual(FakeClient.calls.pop(), (('mail.update', {'password': 'dummy-password'}), {}))

        dataset = {'name': 'tank/example', 'type': 'FILESYSTEM'}
        properties = {'encryption_options': {'passphrase': 'dummy-password'}}
        variables = {'desired_dataset': dataset, 'truenas_entities_dataset_payload': properties}
        self.run_task(self.task('roles/truenas_entities/tasks/dataset.yml', 'Create dataset'), variables)
        self.assertEqual(FakeClient.calls.pop(), (('pool.dataset.create', {**properties, **dataset}), {}))
        self.run_task(self.task('roles/truenas_entities/tasks/dataset.yml', 'Update dataset'), variables)
        self.assertEqual(FakeClient.calls.pop(), (('pool.dataset.update', 'tank/example', properties), {}))

        for custom in (True, False):
            config = {'password': 'dummy-password'}
            app = {'name': 'example', 'custom_app': custom, 'custom_compose_config': config,
                   'values': config, 'catalog_app': 'example'}
            task = self.task('roles/truenas_entities/tasks/app.yml', 'Create application')
            self.run_task(task, {'desired_app': app})
            args, kwargs = FakeClient.calls.pop()
            self.assertEqual(args[0], 'app.create')
            self.assertEqual(args[1]['custom_compose_config' if custom else 'values'], config)
            self.assertEqual(kwargs, {'job': True, 'timeout': None})
            task = self.task('roles/truenas_entities/tasks/app.yml', 'Update application')
            self.run_task(task, {'desired_app': app, 'truenas_entities_app_config': config})
            args, kwargs = FakeClient.calls.pop()
            self.assertEqual(args, ('app.update', 'example',
                                    {'custom_compose_config' if custom else 'values': config}))
            self.assertEqual(kwargs, {'job': True, 'timeout': None})

    def test_tdarr_update_waits_for_job(self):
        module = load_script('files/tdarr/youtube-library.py')
        config = {'environment': {'password': 'dummy-password'}}
        module.update_app(config)
        self.assertEqual(FakeClient.calls, [(('app.update', 'tdarr', {'custom_compose_config': config}),
                                             {'job': True, 'timeout': None})])

    def test_export_flags_publication_and_cleanup(self):
        module = load_script('files/backup-config.py')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'backup.tar'
            with patch.object(module.urllib.request, 'urlopen', return_value=io.BytesIO(b'archive')) as urlopen:
                module.export(str(target))
            self.assertEqual(target.read_bytes(), b'archive')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(FakeClient.calls[1][0][2],
                             [{'secretseed': True, 'pool_keys': False, 'root_authorized_keys': True}])
            urlopen.assert_called_once_with('http://127.0.0.1:85/download?token=dummy-token', timeout=120)
            with self.assertRaises(FileExistsError):
                module.publish(target, lambda output: output.write(b'replacement'))
            self.assertEqual(target.read_bytes(), b'archive')
            target.unlink()
            other = Path(directory) / 'other'
            other.write_bytes(b'unchanged')
            target.symlink_to(other)
            with self.assertRaises(FileExistsError):
                module.publish(target, lambda output: output.write(b'unsafe'))
            self.assertEqual(other.read_bytes(), b'unchanged')
            target.unlink()

            def fail(output):
                output.write(b'partial')
                raise OSError('synthetic failure')

            with self.assertRaises(OSError):
                module.publish(target, fail)
            self.assertFalse(target.exists())
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['other'])

    def test_unprotected_parent_is_refused(self):
        module = load_script('files/backup-config.py')
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'unprotected'
            parent.mkdir(mode=0o777)
            parent.chmod(0o777)
            with self.assertRaises(ValueError):
                module.publish(parent / 'backup.tar', lambda output: output.write(b'archive'))
            self.assertEqual(list(parent.iterdir()), [])

    def test_configuration_queries_do_not_log_results(self):
        for path in (ROOT / 'playbooks').glob('*.yml'):
            for play in yaml.safe_load(path.read_text()):
                for task in play.get('tasks', []):
                    text = json.dumps(task)
                    if 'retrieve_config' in text:
                        self.assertTrue(task.get('no_log'), f'{path}: {task["name"]}')
        discovery = yaml.safe_load((ROOT / 'playbooks/discover.yml').read_text())[0]['tasks'][0]
        self.assertTrue(discovery['no_log'])

    def test_backup_commands_use_stdin_and_cleanup(self):
        block = yaml.safe_load((ROOT / 'playbooks/backup.yml').read_text())[0]['tasks'][0]
        export = block['block'][0]
        publish = block['block'][3]
        for task in (export, publish):
            command = task['ansible.builtin.command']
            self.assertTrue(task['no_log'])
            self.assertEqual(command['argv'][:2], ['/usr/bin/python3', '-c'])
            self.assertIn('backup-config.py', command['argv'][2])
            self.assertIn('stdin', command)
        self.assertEqual(len(block['always']), 2)
        self.assertIn('truenas_backup_export is succeeded', block['always'][1]['when'])


if __name__ == '__main__':
    unittest.main()
