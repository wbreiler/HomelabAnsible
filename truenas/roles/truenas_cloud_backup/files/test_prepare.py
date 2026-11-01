"""Exercise a committed WAL transaction and exclusion boundaries."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).with_name('prepare.py'))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class MediaCatalogTest(unittest.TestCase):
    def test_inventory_includes_all_libraries_and_skips_links_and_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'media'
            for name in ('movies', 'tv', 'anime', 'music'):
                folder = source / name / 'Title with "quotes" and 日本語'
                folder.mkdir(parents=True)
                (folder / 'file.media').write_bytes(b'media')
            (source / 'empty.txt').touch()
            (source / '.zfs').mkdir()
            (source / '.zfs' / 'snapshot.mkv').write_bytes(b'old')
            (source / 'linked-file').symlink_to(source / 'empty.txt')
            (source / 'linked-directory').symlink_to(source / 'movies', target_is_directory=True)
            os.mkfifo(source / 'pipe')
            target = root / 'backups' / 'media-catalog.json'
            self.assertEqual(prepare.catalog_media(source, target), 5)
            catalog = json.loads(target.read_text())
            self.assertEqual(catalog['schema_version'], 1)
            self.assertEqual(catalog['file_count'], 5)
            self.assertEqual(catalog['size_bytes'], 20)
            self.assertEqual(set(catalog['libraries']), {'movies', 'tv', 'anime', 'music', '_root'})
            self.assertEqual(catalog['libraries']['music'], {'file_count': 1, 'size_bytes': 5})
            self.assertTrue(any('日本語' in item['path'] for item in catalog['files']))
            self.assertTrue(all(item['modified_at'].endswith('+00:00') for item in catalog['files']))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_failed_scan_preserves_previous_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'media'
            source.mkdir()
            target = root / 'media-catalog.json'
            target.write_text('previous catalog')

            def unreadable(*args, **kwargs):
                kwargs['onerror'](PermissionError('unreadable library'))

            with patch.object(prepare.os, 'walk', side_effect=unreadable):
                with self.assertRaises(PermissionError):
                    prepare.catalog_media(source, target)
            with self.assertRaises(RuntimeError):
                prepare.catalog_media(source / 'missing', target)
            self.assertEqual(target.read_text(), 'previous catalog')

    def test_failed_publication_preserves_previous_catalog_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'media'
            source.mkdir()
            target = root / 'media-catalog.json'
            target.write_text('previous catalog')
            with patch.object(prepare.os, 'replace', side_effect=OSError('write failed')):
                with self.assertRaises(OSError):
                    prepare.catalog_media(source, target)
            self.assertEqual(target.read_text(), 'previous catalog')
            self.assertEqual(list(root.glob('.media-catalog-*')), [])
            with self.assertRaises(RuntimeError):
                prepare.catalog_media(source, source / 'catalog.json')


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
