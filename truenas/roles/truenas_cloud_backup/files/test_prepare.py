"""Exercise a committed WAL transaction and exclusion boundaries."""
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).with_name('prepare.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class SQLiteBackupTest(unittest.TestCase):
    def test_wal_content_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'appdata'
            source.mkdir()
            database = source / 'service.db'
            with sqlite3.connect(database) as original:
                original.execute('PRAGMA journal_mode=WAL')
                original.execute('CREATE TABLE records (value TEXT)')
                original.execute("INSERT INTO records VALUES ('committed WAL data')")
                original.commit()
                (source / 'lancache').mkdir()
                (source / 'lancache' / 'cache.db').write_bytes(database.read_bytes())
                (source / 'external.db').symlink_to(database)
                (source / 'opaque.db').write_bytes(b'not a SQLite database')
                destination = root / 'copies'
                self.assertEqual(prepare.backup_sqlite(source, destination), 1)
                with closing(sqlite3.connect(destination / 'service.db')) as restored:
                    self.assertEqual(restored.execute('SELECT value FROM records').fetchone(), ('committed WAL data',))
                self.assertEqual(sorted(p.name for p in destination.iterdir()), ['service.db'])
                self.assertEqual((destination / 'service.db').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
