#!/usr/bin/python3
"""Wait for one clips upload, restore three files, and compare SHA-256 hashes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import time

from run import ROOT, notify


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(client, job_id, source, destination):
    while True:
        jobs = client.call('core.get_jobs', [['id', '=', job_id]])
        if len(jobs) != 1 or jobs[0]['method'] != 'cloud_backup.sync' or jobs[0]['arguments'][0] != 2:
            raise RuntimeError('Expected clips upload job is missing or changed')
        job = jobs[0]
        if job['state'] == 'SUCCESS':
            break
        if job['state'] not in ('WAITING', 'RUNNING'):
            raise RuntimeError('Clips upload did not succeed; restore test stopped')
        time.sleep(30)
    task = client.call('cloud_backup.get_instance', 2)
    if task['path'] != str(source) or task['attributes']['bucket'] != 'truenas-backup' or task['attributes']['folder'] != 'clips':
        raise RuntimeError('Unexpected clips backup configuration')
    snapshots = client.call('cloud_backup.list_snapshots', 2)
    snapshot = max(snapshots, key=lambda s: s['time'])
    if snapshot['time'] < job['time_started']:
        raise RuntimeError('No snapshot from the completed clips upload')
    if len(snapshot['paths']) != 1:
        raise RuntimeError('Unexpected clips snapshot paths')
    # Native relative-path backups record source paths in metadata but store files at /.
    root = PurePosixPath('/')
    pending, candidates = [str(root)], []
    while pending and len(candidates) < 3:
        for entry in client.call('cloud_backup.list_snapshot_directory', 2, snapshot['id'], pending.pop(0)):
            path = PurePosixPath(entry['path'])
            relative = path.relative_to(root)
            if '..' in relative.parts or any(c in str(relative) for c in '*?[]\\'):
                continue
            if entry['type'] == 'dir' and path != root:
                pending.append(str(path))
            elif entry['type'] == 'file' and path.suffix.lower() in ('.mp4', '.mkv', '.mov', '.webm', '.m4v', '.avi') and 0 < entry['size'] <= 256 * 1024**2:
                original = source / str(relative)
                if original.is_file() and not original.is_symlink() and original.resolve().is_relative_to(source.resolve()):
                    candidates.append((relative, entry['size']))
    if len(candidates) < 3:
        raise RuntimeError('Need three nonempty clips of at most 256 MiB for the sample')
    candidates.sort(key=lambda item: item[1])
    sample = [candidates[0], candidates[len(candidates) // 2], candidates[-1]]
    before = {str(path): digest(source / str(path)) for path, _ in sample}
    client.call('cloud_backup.restore', 2, snapshot['id'], str(root), str(destination),
                {'include': ['/' + str(path) for path, _ in sample]}, job=True, timeout=None)
    files = []
    for path, size in sample:
        relative = str(path)
        restored = destination / relative
        original = source / relative
        if restored.is_symlink() or not restored.resolve().is_relative_to(destination.resolve()):
            raise RuntimeError('Unsafe restored file path')
        restored_hash = digest(restored)
        if restored.stat().st_size != size or restored_hash != before[relative] or digest(original) != before[relative]:
            raise RuntimeError('Restored file differs or original changed during verification')
        files.append({'path': relative, 'bytes': size, 'original_sha256': before[relative], 'restored_sha256': restored_hash})
    return {'snapshot_id': snapshot['id'], 'files': files, 'restored_directory': str(destination)}


def main():
    from truenas_api_client import Client
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', type=int, required=True)
    args = parser.parse_args()
    result = {'upload_job_id': args.job_id, 'started': datetime.now(timezone.utc).isoformat()}
    try:
        parent = ROOT / 'restore-test'
        parent.mkdir(mode=0o700, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix='clips-', dir=parent))
        with Client() as client:
            result.update(verify(client, args.job_id, Path('/mnt/gaia/clips'), destination))
        result['passed'] = True
        message = 'TrueNAS clips restore test PASSED: three real clips restored from IDrive e2; all SHA-256 hashes match the originals.'
    except Exception as error:
        result.update(passed=False, error_type=type(error).__name__)
        if type(error) is RuntimeError:
            result['error'] = str(error)
        message = 'TrueNAS clips restore test FAILED or could not run. Inspect the protected clips-restore-test.json report and native restore job.'
    result['finished'] = datetime.now(timezone.utc).isoformat()
    (ROOT / 'clips-restore-test.json').write_text(json.dumps(result, indent=2) + '\n')
    print(message, flush=True)
    webhook = json.loads((ROOT / 'discord.json').read_text())['webhook']
    notify(webhook, message)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
