import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location('verify_clips', Path(__file__).with_name('verify_clips.py'))
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class FakeClient:
    def __init__(self, source, corrupt=False, state='SUCCESS'):
        self.source, self.corrupt, self.state = source, corrupt, state
        self.restored = False

    def call(self, method, *args, **kwargs):
        if method == 'core.get_jobs':
            return [{'method': 'cloud_backup.sync', 'arguments': [2, {}], 'state': self.state, 'time_started': 1}]
        if method == 'cloud_backup.get_instance':
            return {'path': str(self.source), 'attributes': {'bucket': 'truenas-backup', 'folder': 'clips'}}
        if method == 'cloud_backup.list_snapshots':
            return [{'id': 'abc', 'time': 2, 'paths': ['/snapshot/clips']}]
        if method == 'cloud_backup.list_snapshot_directory':
            return [{'path': '/' + p.name, 'type': 'file', 'size': p.stat().st_size}
                    for p in self.source.iterdir()]
        if method == 'cloud_backup.restore':
            self.restored = True
            destination = Path(args[3])
            for p in self.source.iterdir():
                (destination / p.name).write_bytes(b'bad' if self.corrupt else p.read_bytes())
            return
        raise AssertionError(method)


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.target = Path(self.temp.name) / 'restore'
        self.source.mkdir()
        self.target.mkdir()
        for i in range(3):
            (self.source / f'{i}.mp4').write_bytes(bytes([i]) * (i + 1))

    def test_restored_hashes_match(self):
        result = verifier.verify(FakeClient(self.source), 80875, self.source, self.target)
        self.assertEqual(len(result['files']), 3)
        for file in result['files']:
            self.assertEqual(file['original_sha256'], file['restored_sha256'])

    def test_corruption_fails_verification(self):
        with self.assertRaises(RuntimeError):
            verifier.verify(FakeClient(self.source, corrupt=True), 80875, self.source, self.target)

    def test_failed_upload_never_restores(self):
        client = FakeClient(self.source, state='FAILED')
        with self.assertRaises(RuntimeError):
            verifier.verify(client, 80875, self.source, self.target)
        self.assertFalse(client.restored)


if __name__ == '__main__':
    unittest.main()
