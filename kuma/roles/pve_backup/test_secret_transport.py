"""Check that PBS credentials reach the prompt, never the command line."""
from pathlib import Path
import shlex
import unittest

import jinja2
import yaml


class PasswordTransportTests(unittest.TestCase):
    def test_password_only_enters_prompt_response(self):
        tasks = yaml.safe_load((Path(__file__).parent / 'tasks/main.yml').read_text())
        task = next(item for item in tasks if 'ansible.builtin.expect' in item)
        values = {
            'pve_backup_storage_id': 'kuma-backup',
            'pve_backup_pbs_server': 'backup.example',
            'pve_backup_pbs_datastore': 'store',
            'pve_backup_pbs_namespace': 'kuma/site',
            'pve_backup_pbs_username': 'backup user; literal@pbs',
            'pve_backup_pbs_fingerprint': '00:' * 31 + '00',
            'pve_backup_pbs_password': 'dummy-password-with-"quotes"',
        }
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined)
        environment.filters['quote'] = shlex.quote
        config = task['ansible.builtin.expect']
        command = environment.from_string(config['command']).render(**values)
        argv = shlex.split(command)
        self.assertNotIn(values['pve_backup_pbs_password'], command)
        self.assertEqual(argv[-1], '--password')
        self.assertEqual(argv[argv.index('--username') + 1], values['pve_backup_pbs_username'])
        response = environment.from_string(config['responses']['(?i)password:']).render(**values)
        self.assertEqual(response, values['pve_backup_pbs_password'])
        self.assertTrue(task['no_log'])
        self.assertFalse(config['echo'])
        self.assertEqual(task['when'], 'pve_backup_storage_check.rc != 0')


if __name__ == '__main__':
    unittest.main()
