import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pxe_install as pxe
from test_iso_install import example


def specification(family='debian'):
    return dict(example(family), firmware='uefi', secure_boot=True, memory_mb=8192,
                pxe_server={'host': '192.0.2.10', 'http_url': 'http://192.0.2.10',
                            'ssh_public_key_file': str(Path(__file__).parent / 'install.pub')})


class PxeTests(unittest.TestCase):
    def test_payloads_keep_identity_disk_guards_and_remove_cdrom(self):
        for family in ('debian', 'ubuntu', 'fedora'):
            with self.subTest(family=family):
                spec = specification(family)
                files, script = pxe.payloads(spec, 'http://192.0.2.10/images/pinned')
                seed = files[{'debian': 'preseed.cfg', 'ubuntu': 'user-data', 'fedora': 'ks.cfg'}[family]].decode()
                self.assertIn('/sys/class/dmi/id/product_uuid', seed)
                self.assertIn(spec['uuid'], seed)
                self.assertIn('/dev/sda' if family != 'fedora' else '--only-use=sda', seed)
                if family == 'debian':
                    self.assertIn('drive-scsi0', seed)
                    self.assertIn('debconf-set partman-auto/disk "$disk"', seed)
                    self.assertNotIn('partman-auto/disk string /dev/sda', seed)
                self.assertNotIn('/cdrom/terraform', seed)
                self.assertNotIn('/run/install/repo/terraform', seed)
                self.assertIn('/bootstrap.sh', seed)
                self.assertIn('iseq ${uuid} ' + spec['uuid'], script)
                self.assertIn('shim http://192.0.2.10/images/pinned/shim.efi', script)
                self.assertIn('initrd --name initrd', script)

    def test_input_boundaries(self):
        for fields in ({'firmware': 'bios', 'secure_boot': False}, {'os': 'ubuntu', 'memory_mb': 2048},
                       {'pxe_server': dict(specification()['pxe_server'], host='host;command')},
                       {'pxe_server': dict(specification()['pxe_server'], http_url='http://host/;command')}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                pxe.validate(dict(specification(), **fields))

    def test_entry_is_retired_only_after_successful_verification(self):
        spec = specification()
        with patch.object(pxe.iso, 'wait', side_effect=RuntimeError('not installed')), patch.object(pxe, 'remote') as remote:
            with self.assertRaises(RuntimeError):
                pxe.wait(spec)
            remote.assert_not_called()
        with patch.object(pxe.iso, 'wait'), patch.object(pxe, 'remote') as remote:
            pxe.wait(spec)
            self.assertEqual(remote.call_args.args[1], f'touch /srv/pxe/install/{spec["uuid"]}/.installed && rm -f /srv/pxe/boot/{spec["uuid"]}.ipxe')

    def test_asset_cache_is_atomic_and_rejects_modified_files(self):
        spec = specification('ubuntu')
        def extract(command):
            if '-find' in command:
                return "'/EFI/BOOT/BOOTX64.EFI'\n"
            Path(command[-1]).write_bytes(command[-2].encode())
            return ''
        with tempfile.TemporaryDirectory() as directory, patch.object(pxe.iso, 'source_iso', return_value=Path('source.iso')):
            root = Path(directory) / 'pxe'
            with patch.object(pxe.iso, 'run', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    pxe.assets(spec, root)
            self.assertFalse(any(p.is_dir() for p in (root / 'images').iterdir()))
            with patch.object(pxe.iso, 'run', side_effect=extract):
                identity, image = pxe.assets(spec, root)
            with patch.object(pxe.iso, 'run') as run:
                self.assertEqual(pxe.assets(spec, root), (identity, image))
                run.assert_not_called()
                (image / 'linux').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    pxe.assets(spec, root)

    def test_publishing_cannot_rearm_a_completed_installation(self):
        for completed in (False, True):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec = specification()
                spec['output_iso'] = str(root / 'artifacts/iso-install' / spec['uuid'] / 'autoinstall.iso')
                image = root / 'image'
                image.mkdir()
                (image / 'initrd.gz').write_bytes(b'initrd')
                server = root / 'server'
                (server / 'boot').mkdir(parents=True)
                install = server / 'install' / spec['uuid']
                install.mkdir(parents=True)
                entry = server / 'boot' / (spec['uuid'] + '.ipxe')
                if completed:
                    (install / '.installed').touch()
                    entry.write_text('stale entry')
                def remote(_spec, command, data=None):
                    pxe.subprocess.run(['sh', '-c', command.replace('/srv/pxe', str(server))], input=data, text=True, check=True)
                with patch.object(pxe, 'assets', return_value=('image', image)), patch.object(pxe, 'upload'), patch.object(pxe, 'remote', side_effect=remote):
                    pxe.build(spec)
                self.assertEqual(entry.exists(), not completed)
                self.assertEqual((install / '.installed').exists(), completed)

    def test_library_refuses_to_overwrite_existing_wrong_media(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'test.iso'
            target.write_bytes(b'original recovery media')
            program = pxe.SYNC_LIBRARY.replace("'/srv/pxe/iso'", repr(directory))
            spec = {'files': {'test.iso': 'a' * 64}, 'base_url': 'http://iso.example'}
            with patch('sys.stdin', io.StringIO(json.dumps(spec))), patch('urllib.request.urlopen') as download:
                with self.assertRaisesRegex(ValueError, 'Existing ISO checksum mismatch'):
                    exec(program, {})
                download.assert_not_called()
            self.assertEqual(target.read_bytes(), b'original recovery media')

    def test_library_rejects_invalid_paths_and_checksums(self):
        for name, checksum in [('../escape.iso', 'a' * 64), ('test.iso', 'invalid')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                program = pxe.SYNC_LIBRARY.replace("'/srv/pxe/iso'", repr(directory))
                spec = {'files': {name: checksum}, 'base_url': 'http://iso.example'}
                with patch('sys.stdin', io.StringIO(json.dumps(spec))), patch('urllib.request.urlopen') as download:
                    with self.assertRaises(ValueError):
                        exec(compile(program, '<sync-library>', 'exec', optimize=2), {})
                    download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
