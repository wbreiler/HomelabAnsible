#!/usr/bin/python3
"""Run native TrueNAS backup scopes in sequence and report their outcome."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

ROOT = Path('/mnt/gaia/appdata/_cloud-backup')
SCOPES = ('system-config', 'app-settings', 'appdata', 'clips', 'archive')
CRON_DESCRIPTION = 'IDrive e2 nightly backups'
CRON_COMMAND = '/usr/bin/python3 /mnt/gaia/appdata/_cloud-backup/run.py'


def run_backups(client, initial=False):
    tasks = client.call('cloud_backup.query')
    selected = []
    for scope in SCOPES:
        matches = [task for task in tasks if task['description'] == 'IDrive e2: ' + scope]
        if len(matches) != 1:
            raise RuntimeError('Backup scope is missing or duplicated: ' + scope)
        task = matches[0]
        if task['attributes']['bucket'] != 'truenas-backup' or task['attributes']['folder'] != scope or task['keep_last'] != 30:
            raise RuntimeError('Unexpected repository or retention for scope: ' + scope)
        if task['enabled']:
            raise RuntimeError('Disable per-scope schedules before using the sequential runner')
        if scope == 'archive' and 'YouTube' not in task['exclude']:
            raise RuntimeError('Archive backup must exclude YouTube')
        selected.append((scope, task['id']))
    completed = []
    for scope, task_id in selected:
        print('Starting native backup scope: ' + scope, flush=True)
        client.call('cloud_backup.sync', task_id, {}, job=True, timeout=None)
        completed.append(scope)
        print('Completed native backup scope: ' + scope, flush=True)
    if initial:
        desired = {
            'description': CRON_DESCRIPTION, 'command': CRON_COMMAND,
            'user': 'root', 'enabled': True, 'stdout': True, 'stderr': False,
            'schedule': {'minute': '0', 'hour': '4', 'dom': '*', 'month': '*', 'dow': '*'},
        }
        existing = client.call('cronjob.query', [['description', '=', CRON_DESCRIPTION]])
        if len(existing) > 1:
            raise RuntimeError('Duplicate nightly backup schedules require review')
        if existing:
            client.call('cronjob.update', existing[0]['id'], desired)
        else:
            client.call('cronjob.create', desired)
        print('Enabled nightly backups at 04:00 America/Chicago', flush=True)
    return completed


def notify(webhook, content):
    request = urllib.request.Request(
        webhook, method='POST',
        data=json.dumps({'username': 'TrueNAS Backups', 'content': content, 'allowed_mentions': {'parse': []}}).encode(),
        headers={'Content-Type': 'application/json', 'User-Agent': 'TrueNAS-Cloud-Backup/1.0'},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except Exception as error:
        # Never log the access-bearing webhook URL or request details.
        raise RuntimeError('Discord delivery failed: ' + type(error).__name__) from None


def main():
    from truenas_api_client import Client
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial', action='store_true')
    parser.add_argument('--test-notification', action='store_true')
    args = parser.parse_args()
    webhook = json.loads((ROOT / 'discord.json').read_text())['webhook']
    if not re.fullmatch(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+', webhook):
        raise RuntimeError('Invalid Discord webhook configuration')
    if args.test_notification:
        notify(webhook, 'TrueNAS IDrive backup notifications are configured. This is a delivery test; no full backup has completed yet.')
        print('Discord test notification delivered', flush=True)
        return
    with (ROOT / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A TrueNAS cloud backup is already running; skipping overlap', flush=True)
            return
        result = {'initial': args.initial, 'started': datetime.now(timezone.utc).isoformat()}
        try:
            with Client() as client:
                result['completed'] = run_backups(client, args.initial)
            result['passed'] = True
        except Exception as error:
            # Native job errors can contain access-bearing URLs. Keep the details in the protected TrueNAS job log.
            result.update(passed=False, error_type=type(error).__name__)
            print('Backup failed; inspect the native TrueNAS Cloud Backup job log. Nightly activation did not complete.', flush=True)
        result['finished'] = datetime.now(timezone.utc).isoformat()
        (ROOT / 'last-run.json').write_text(json.dumps(result, indent=2) + '\n')
        if args.initial:
            (ROOT / 'initial-run.json').write_text(json.dumps(result, indent=2) + '\n')
        if result['passed']:
            message = 'TrueNAS IDrive backup completed successfully: all five scopes. Retention: 30 versions per scope.'
            if args.initial:
                message += ' Initial upload complete. Nightly backups are now enabled for 04:00 Central.'
        else:
            message = 'TrueNAS IDrive backup FAILED. Check Data Protection → Cloud Backup Tasks on erebus.'
            if args.initial:
                message += ' The initial run did not complete; nightly backups remain disabled.'
        notify(webhook, message)
        if not result['passed']:
            sys.exit(1)


if __name__ == '__main__':
    main()
