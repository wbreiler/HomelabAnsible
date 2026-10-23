import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('run', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FakeClient:
    def __init__(self, fail_scope=None):
        self.fail_scope = fail_scope
        self.completed = []
        self.schedule = None

    def call(self, method, *args, **kwargs):
        if method == 'cloud_backup.query':
            return [{'id': scope, 'description': 'IDrive e2: ' + scope,
                     'attributes': {'bucket': 'truenas-backup', 'folder': scope},
                     'keep_last': 30, 'enabled': False, 'exclude': ['YouTube']}
                    for scope in runner.SCOPES]
        if method == 'cloud_backup.sync':
            if args[0] == self.fail_scope:
                raise RuntimeError('Synthetic upload failure')
            self.completed.append(args[0])
        elif method == 'cronjob.query':
            return []
        elif method == 'cronjob.create':
            if self.completed != list(runner.SCOPES):
                raise AssertionError('Schedule activated before every scope succeeded')
            self.schedule = args[0]
        else:
            raise AssertionError('Unexpected API call: ' + method)


class ScheduleGateTest(unittest.TestCase):
    def test_success_enables_nightly_after_all_scopes(self):
        client = FakeClient()
        self.assertEqual(runner.run_backups(client, initial=True), list(runner.SCOPES))
        self.assertTrue(client.schedule['enabled'])
        self.assertEqual(client.schedule['schedule']['hour'], '4')

    def test_failure_stops_later_scopes_and_leaves_schedule_absent(self):
        client = FakeClient(fail_scope='appdata')
        with self.assertRaises(RuntimeError):
            runner.run_backups(client, initial=True)
        self.assertEqual(client.completed, ['system-config', 'app-settings'])
        self.assertIsNone(client.schedule)


if __name__ == '__main__':
    unittest.main()
