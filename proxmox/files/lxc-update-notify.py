#!/usr/bin/python3
"""Send bounded maintenance summaries without forwarding logs or credentials."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request


JOBS = {
    'os': ('lxc-auto-update.service', '/var/lib/lxc-auto-update/last-run.json'),
    'apps': ('lxc-app-updates.service', '/var/lib/homelab-app-updates/last-run.json'),
}
WEBHOOK = re.compile(r'https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('notification redirects are forbidden')


def display(value):
    return re.sub(r'[\\`*_~|<>\[\]]', '', ' '.join(str(value).split()))[:80]


def app_name(name):
    return display({
        'pocket_id': 'Pocket ID', 'open_webui': 'Open WebUI',
        'netboot_xyz': 'netboot.xyz', 'sabnzbd': 'SABnzbd',
        'packages': 'Managed packages', 'OS packages': 'OS packages',
    }.get(name, name.replace('_', ' ').title()))


def container_label(row):
    name = display(row.get('name') or '')
    identifier = f'CT {display(row["vmid"])}'
    return f'{name} ({identifier})' if name else identifier


def detail_field(name, lines):
    shown = []
    for line in lines:
        if len('\n\n'.join(shown + [line])) > 900:
            break
        shown.append(line)
    omitted = len(lines) - len(shown)
    if omitted:
        shown.append(f'… and {omitted} more. See the service log.')
    return {'name': name, 'value': '\n\n'.join(shown)}, bool(omitted)


def summary(kind, result, report, invocation, node):
    service, _ = JOBS[kind]
    current = bool(invocation) and report.get('invocation_id') == invocation
    rows = report.get('results', []) if current else []
    failed = [row for row in rows if row['status'] == 'failed']
    updated = [row for row in rows if row['status'] == 'updated']
    success = result == 'success' and not failed and current
    embed = {
        'author': {'name': f'{display(node)} · {"Applications" if kind == "apps" else "OS packages"}'},
        'title': '✅ Maintenance complete' if success else '⚠️ Review required',
        'description': '',
        'color': 0x2ECC71 if success else 0xE74C3C,
        'fields': [],
        'footer': {'text': 'Homelab maintenance'},
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    fields = embed['fields']
    if current:
        done = sum(row['status'] == 'completed' for row in rows)
        skipped = sum(row['status'] == 'skipped' for row in rows)
        if kind == 'os':
            counts = [('completed', done), ('failed', len(failed)), ('skipped', skipped)]
            if success:
                embed['title'] = f'✅ {done} container{"s" if done != 1 else ""} checked'
        else:
            apps = sum(row['app'] != 'packages' for row in updated)
            packages = sum(len(row.get('targets', {})) for row in updated if row['app'] == 'packages')
            counts = [('app' if apps == 1 else 'apps', apps),
                      ('package' if packages == 1 else 'packages', packages), ('failed', len(failed))]
            if success:
                total = apps + packages
                embed['title'] = f'✅ {total} update{"s" if total != 1 else ""} installed'
                if not updated:
                    embed['title'] = '✓ No eligible updates'
                    embed['color'] = 0x5865F2
        embed['description'] = '  ·  '.join(f'**{count}** {label}' for label, count in counts if count)
        if not embed['description']:
            embed['description'] = 'No eligible changes in this run.' if kind == 'apps' else 'No containers selected.'
    else:
        embed['description'] = 'No report from this run. Check the service log below.'

    # Allowlist fields only. Exceptions and logs can contain private details.
    failures = [f'**{app_name(row.get("app", "OS packages"))}** · `{container_label(row)}`' for row in failed]
    changes = []
    for row in updated:
        heading = f'**{app_name(row["app"])}** · `{container_label(row)}`'
        if row['app'] == 'packages':
            versions = '\n'.join(f'{app_name(name)} `{display(version)}`' for name, version in sorted(row.get('targets', {}).items()))
        else:
            versions = f'Version `{display(row.get("current", "unknown"))}`'
        changes.append(f'{heading}\n{versions}')
    truncated = False
    for name, lines in [('Needs attention', failures), ('Updated', changes)]:
        if lines:
            field, omitted = detail_field(name, lines)
            fields.append(field)
            truncated |= omitted
    if not success or truncated:
        action = f'```sh\njournalctl -u {service} -n 80\n```'
        if not success and not failed:
            action = f'Service result: `{display(result)}`\n' + action
        fields.append({'name': f'{"Review" if not success else "Full log"} on {display(node)}', 'value': action})
    return embed


def send(url, message):
    if not WEBHOOK.fullmatch(url):
        raise ValueError('invalid Discord webhook destination')
    payload = json.dumps({'embeds': [message], 'allowed_mentions': {'parse': []}}).encode()
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
            rows = ([{'vmid': 100, 'name': 'pocketid-nash', 'status': 'completed'},
                     {'vmid': 101, 'name': 'npm-nash', 'status': 'skipped'}] if args.kind == 'os' else [
                {'vmid': 100, 'name': 'pocketid-nash', 'app': 'pocket_id', 'status': 'updated', 'current': '2.19.1'},
                {'vmid': 127, 'name': 'loki-nash', 'app': 'packages', 'status': 'updated', 'targets': {'grafana': '13.3.0', 'loki': '3.7.9'}},
                {'vmid': 103, 'name': 'forgejo-nash', 'app': 'forgejo', 'status': 'failed'},
            ])
            result = 'exit-code' if any(row['status'] == 'failed' for row in rows) else 'success'
            message = summary(args.kind, result, {'invocation_id': 'preview', 'results': rows}, 'preview', node)
            message['title'] = 'TEST PREVIEW · ' + message['title']
            message['description'] = '**Sample data only. No updates ran.**\n\n' + message['description']
        else:
            try:
                report = json.loads(Path(JOBS[args.kind][1]).read_text())
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
