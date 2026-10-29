#!/usr/bin/python3
"""Export or publish a configuration archive without exposing its download URL."""
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import urllib.request


def publish(target, writer):
    target = Path(target)
    if not target.is_absolute() or target.name in ('', '.', '..'):
        raise ValueError('Backup path must be an absolute file path')
    parent = target.parent.resolve(strict=True)
    for directory in (target.parent, *target.parent.parents, parent, *parent.parents):
        info = directory.lstat()
        if info.st_uid not in (0, os.geteuid()) or (
            not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX
        ):
            raise ValueError('Backup parent directory is not protected')
    with tempfile.TemporaryDirectory(prefix='.truenas-backup-', dir=parent) as temporary:
        staged = Path(temporary) / 'config.tar'
        with staged.open('xb') as output:
            os.chmod(staged, 0o600)
            writer(output)
        # Link publishes atomically and refuses any existing file or symlink.
        os.link(staged, parent / target.name)


def export(target):
    from truenas_api_client import Client

    with Client() as client:
        port = client.call('system.general.config')['ui_port']
        _, url = client.call('core.download', 'config.save', [
            {'secretseed': True, 'pool_keys': False, 'root_authorized_keys': True}
        ], 'truenas-config.tar', True)

    def download(output):
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{url}', timeout=120) as response:
            shutil.copyfileobj(response, output)

    publish(target, download)


def main():
    os.umask(0o077)
    data = json.load(sys.stdin)
    if data['mode'] == 'export':
        export(data['target'])
    elif data['mode'] == 'publish':
        with open(data['source'], 'rb') as source:
            publish(data['target'], lambda output: shutil.copyfileobj(source, output))
    else:
        raise ValueError('Unsupported backup mode')


if __name__ == '__main__':
    main()
