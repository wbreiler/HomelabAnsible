#!/usr/bin/python3
"""Prepare consistent SQLite copies or a supported TrueNAS configuration export."""
import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import shutil
import subprocess
import uuid
import tempfile
import urllib.request

SKIP = {'lancache', 'ollama', 'standalone-tools', '_cloud-backup', '.zfs'}


def backup_sqlite(source, destination):
    count = 0
    for directory, directories, files in os.walk(source, followlinks=False):
        directories[:] = [d for d in directories if d not in SKIP and not (Path(directory) / d).is_symlink()]
        for filename in files:
            path = Path(directory) / filename
            if path.is_symlink() or path.suffix.lower() not in {'.db', '.sqlite', '.sqlite3'}:
                continue
            with path.open('rb') as stream:
                if stream.read(16) != b'SQLite format 3\0':
                    continue
            target = destination / path.relative_to(source)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.sqlite-')
            os.close(fd)
            try:
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as original:
                    with closing(sqlite3.connect(temporary)) as copied:
                        original.backup(copied)
                        copied.execute('PRAGMA journal_mode=DELETE')
                        try:
                            if copied.execute('PRAGMA quick_check').fetchone() != ('ok',):
                                raise RuntimeError('SQLite backup integrity check failed')
                        except sqlite3.OperationalError as error:
                            if 'no such collation sequence' not in str(error) or not path.is_relative_to(Path('/mnt/gaia/appdata/plex/config')):
                                raise
                            # Plex's own SQLite provides its required ICU collations.
                            container_copy = '/tmp/truenas-cloud-backup-' + uuid.uuid4().hex + '.db'
                            try:
                                subprocess.run(['docker', 'cp', temporary, 'ix-plex-plex-1:' + container_copy], check=True, capture_output=True)
                                result = subprocess.run(['docker', 'exec', '--user', '0', 'ix-plex-plex-1', '/usr/lib/plexmediaserver/Plex SQLite', '-readonly', container_copy, 'PRAGMA quick_check;'], check=True, capture_output=True, text=True)
                                if result.stdout.strip() != 'ok':
                                    raise RuntimeError('Plex SQLite backup integrity check failed')
                            finally:
                                subprocess.run(['docker', 'exec', '--user', '0', 'ix-plex-plex-1', 'rm', '-f', container_copy], check=True, capture_output=True)
                os.replace(temporary, target)
            finally:
                for suffix in ('', '-wal', '-shm'):
                    Path(temporary + suffix).unlink(missing_ok=True)
            count += 1
    return count


def export_config(target):
    from truenas_api_client import Client
    with Client() as client:
        port = client.call('system.general.config')['ui_port']
        _, url = client.call('core.download', 'config.save', [
            {'secretseed': True, 'pool_keys': True, 'root_authorized_keys': True}
        ], 'truenas-config.tar', True)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.config-')
    try:
        with os.fdopen(fd, 'wb') as output:
            # Keep the access-bearing URL out of process arguments and logs.
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{url}', timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['sqlite', 'config', 'apps'])
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.mode == 'sqlite':
        count = backup_sqlite(Path('/mnt/gaia/appdata'), args.destination)
        print(f'Prepared {count} consistent SQLite backups')
    elif args.mode == 'apps':
        args.destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copytree('/mnt/.ix-apps/app_configs', args.destination / 'configs', dirs_exist_ok=True, symlinks=True)
        print('Prepared protected application settings export')
    else:
        export_config(args.destination)
        print('Prepared protected TrueNAS configuration export')


if __name__ == '__main__':
    main()
