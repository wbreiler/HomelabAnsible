"""Native installer archive and existing-release preservation boundaries."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'roles/lxc_app_updates/files/native_apps.py'
SPEC = importlib.util.spec_from_file_location('native_apps', SOURCE)
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


class Preservation(unittest.TestCase):
    def test_archive_cannot_write_outside_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.tar.gz'
            with tarfile.open(source, 'w:gz') as archive:
                member = tarfile.TarInfo('../../escape')
                member.size = 1
                archive.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(tarfile.FilterError):
                native.extract_source(source, root)
            self.assertFalse((root / 'escape').exists())

    def test_release_swap_keeps_old_files_and_refuses_to_overwrite_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, target = root / 'app', root / 'new'
            app.mkdir(); target.mkdir()
            (app / 'config').write_text('preserve')
            native.replace_with_link(app, target, '1.2.3')
            self.assertEqual(app.resolve(), target.resolve())
            self.assertEqual((root / 'app.pre-auto-1.2.3/config').read_text(), 'preserve')
            with self.assertRaisesRegex(RuntimeError, 'backup exists'):
                native.replace_with_link(app, target, '1.2.3')
            self.assertTrue(app.is_symlink())

    def test_netboot_update_preserves_the_managed_signed_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def mapped(value):
                path = Path(value)
                return root / str(path).lstrip('/') if path.is_absolute() else path
            for path in ['srv/tftp', 'etc', 'downloads']:
                (root / path).mkdir(parents=True, exist_ok=True)
            (root / 'etc/netboot-xyz-managed-shim').write_text('2.0.0')
            (root / 'srv/tftp/netboot.xyz.efi').write_bytes(b'signed shim')
            for name in ['netboot.xyz.efi', 'netboot.xyz.kpxe']:
                (root / 'downloads' / name).write_bytes(b'updated ' + name.encode())
            with patch.object(native, 'Path', side_effect=mapped), patch.object(native, 'run'), patch.object(native.sys, 'argv', ['update', 'netboot_xyz', '3.0.4', '/downloads/netboot.xyz.efi']):
                native.main()
            self.assertEqual((root / 'srv/tftp/netboot.xyz.efi').read_bytes(), b'signed shim')
            self.assertEqual((root / 'srv/tftp/netboot.xyz-unsigned.efi').read_bytes(), b'updated netboot.xyz.efi')
            self.assertEqual((root / 'srv/tftp/netboot.xyz.kpxe').read_bytes(), b'updated netboot.xyz.kpxe')

    def test_link_failure_restores_original_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'app'
            app.mkdir()
            (app / 'config').write_text('preserve')
            with patch.object(Path, 'symlink_to', side_effect=OSError('full filesystem')), self.assertRaises(OSError):
                native.replace_with_link(app, root / 'new', '1.2.3')
            self.assertEqual((app / 'config').read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
