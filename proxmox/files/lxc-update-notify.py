#!/usr/bin/python3
"""Send bounded maintenance summaries without forwarding logs or credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request


JOBS = {
    'os': ('LXC package updates', 'lxc-auto-update.service', '/var/lib/lxc-auto-update/last-run.json'),
    'apps': ('LXC application updates', 'lxc-app-updates.service', '/var/lib/homelab-app-updates/last-run.json'),
}
WEBHOOK = re.compile(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('notification redirects are forbidden')


def summary(kind, result, report, invocation, node):
    title, service, _ = JOBS[kind]
    current = bool(invocation) and report.get('invocation_id') == invocation
    rows = report.get('results', []) if current else []
    failed = [row for row in rows if row['status'] == 'failed']
    success = result == 'success' and not failed and current
    lines = [f'{node}: {title} — {"completed" if success else "FAILED"}']
    if current:
        done = sum(row['status'] == 'completed' for row in rows)
        updated = [row for row in rows if row['status'] == 'updated']
        skipped = sum(row['status'] == 'skipped' for row in rows)
        if kind == 'os':
            lines.append(f'{done} guests completed; {len(failed)} failed; {skipped} skipped.')
        else:
            lines.append(f'{len(updated)} app/package updates; {len(failed)} failures.')
        # Allowlist fields only. Exceptions and logs can contain private details.
        for row in failed:
            lines.append(f'FAILED: CT {row["vmid"]} {row.get("app", "OS packages")}')
        for row in updated:
            target = row.get('current') or ', '.join(f'{k}={v}' for k, v in row.get('targets', {}).items())
            lines.append(f'Updated: CT {row["vmid"]} {row["app"]} {target}')
    else:
        lines.append('No report from this run. Inspect the service journal.')
    if not success:
        lines.append(f'Service result: {result}. Manual review required.')
    lines.append(f'Logs: journalctl -u {service}')
    return '\n'.join(lines)[:1900]


def send(url, message):
    if not WEBHOOK.fullmatch(url):
        raise ValueError('invalid Discord webhook destination')
    payload = json.dumps({'content': message, 'allowed_mentions': {'parse': []}}).encode()
    request = urllib.request.Request(url + '?wait=true', data=payload, headers={
        'Content-Type': 'application/json', 'User-Agent': 'HomelabAnsible-maintenance',
    })
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=15) as response:
                if response.status != 200 or not json.load(response).get('id'):
                    raise ValueError('Discord did not confirm message delivery')
            return
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise
            delay = float(error.headers.get('Retry-After', '2'))
            if attempt == 2 or not 0 <= delay <= 10:
                raise
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=JOBS)
    parser.add_argument('--test', action='store_true', help='send a clearly labeled delivery test without updating guests')
    args = parser.parse_args()
    try:
        config = json.loads(Path('/etc/lxc-update-notifications.json').read_text())
        if not config['webhook_url']:
            print('Discord maintenance notifications are disabled')
            return 0
        node = socket.gethostname().split('.')[0]
        if args.test:
            message = f'TEST — {node}: Discord notifications enabled for LXC package and application update results. No updates ran for this test.'
        else:
            try:
                report = json.loads(Path(JOBS[args.kind][2]).read_text())
                if not isinstance(report, dict):
                    report = {}
            except (OSError, ValueError):
                report = {}
            message = summary(args.kind, os.environ.get('SERVICE_RESULT', 'unknown'), report,
                              os.environ.get('INVOCATION_ID', ''), node)
        send(config['webhook_url'], message)
        print('Discord maintenance notification delivered')
        return 0
    except Exception as error:
        # urllib exceptions can contain the entire credential-bearing URL.
        print(f'Discord maintenance notification failed ({type(error).__name__}); credentials omitted')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
