#!/usr/bin/python3
"""Update running local Debian LXCs without changing host packages or power."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import time

REPORT_FILE = Path('/var/lib/lxc-auto-update/last-run.json')


UPDATE = r"""set -eu
umask 022
export DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none NEEDRESTART_MODE=a
apt-get -o DPkg::Lock::Timeout=300 -o APT::Update::Error-Mode=any update
apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef \
  -o Dpkg::Options::=--force-confold --with-new-pkgs --no-remove -y upgrade
if test -f /var/run/reboot-required; then
  echo 'REBOOT REQUIRED: manual maintenance needed'
fi
"""


def command(args):
    return subprocess.check_output(args, text=True).strip()


def api(path, *args):
    return json.loads(command(['pvesh', 'get', path, *args, '--output-format', 'json']))


def recent_backup(backups, vmid, max_age_hours, now):
    return any(
        row.get('subtype') == 'lxc'
        and int(row.get('vmid', 0)) == vmid
        and 0 <= now - row.get('ctime', 0) <= max_age_hours * 3600
        and row.get('verification', {}).get('state') != 'failed'
        for row in backups
    )


def guest(vmid, *args):
    return command(['pct', 'exec', str(vmid), '--', *args])


def failed_services(vmid):
    return set(guest(vmid, 'systemctl', '--failed', '--no-legend', '--plain', '--no-pager').splitlines())


def update_guests(config, dry_run=False, requested=()):
    node = socket.gethostname().split('.')[0]
    guests = api(f'/nodes/{node}/lxc')
    backups = api(f'/nodes/{node}/storage/{config["backup_storage"]}/content', '--content', 'backup')
    failures = []
    report = []
    selected = set()
    for row in guests:
        vmid = int(row['vmid'])
        if requested and vmid not in requested:
            continue
        selected.add(vmid)
        if row['status'] != 'running' or vmid in config['skip_vmids']:
            print(f'SKIP {vmid}: stopped or explicitly excluded', flush=True)
            report.append({'vmid': vmid, 'name': row.get('name', ''), 'status': 'skipped'})
            continue
        try:
            if not recent_backup(backups, vmid, config['backup_max_age_hours'], time.time()):
                raise RuntimeError('no recent usable backup')
            settings = api(f'/nodes/{node}/lxc/{vmid}/config')
            if settings.get('lock'):
                raise RuntimeError('container is locked for another operation')
            # Refuse other package managers instead of silently reporting success.
            guest(vmid, 'sh', '-c', 'command -v apt-get >/dev/null && test -d /run/systemd/system')
            print(f'{"CHECK" if dry_run else "UPDATE"} {vmid}: {row.get("name", "")}', flush=True)
            if dry_run:
                print(guest(vmid, 'apt-get', '--simulate', '--with-new-pkgs', '--no-remove', 'upgrade'), flush=True)
                continue
            before = failed_services(vmid)
            # Do not kill dpkg midway through an upgrade with a process timeout.
            subprocess.run(['pct', 'exec', str(vmid), '--', 'sh', '-c', UPDATE], check=True)
            new_failures = failed_services(vmid) - before
            if new_failures:
                raise RuntimeError('new failed services: ' + ', '.join(sorted(new_failures)))
            print(f'OK {vmid}', flush=True)
            report.append({'vmid': vmid, 'name': row.get('name', ''), 'status': 'completed'})
        except (RuntimeError, subprocess.CalledProcessError) as error:
            failures.append(vmid)
            report.append({'vmid': vmid, 'name': row.get('name', ''), 'status': 'failed'})
            # Do not echo arbitrary command arguments or application configuration.
            detail = str(error) if isinstance(error, RuntimeError) else f'command exited {error.returncode}'
            print(f'FAILED {vmid}: {detail}', flush=True)
    missing = set(requested) - selected
    if missing:
        print(f'FAILED: requested LXCs are not local: {sorted(missing)}', flush=True)
        report.extend({'vmid': vmid, 'status': 'failed'} for vmid in sorted(missing))
    if not dry_run:
        temporary = REPORT_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps({'invocation_id': os.environ.get('INVOCATION_ID'), 'results': report}) + '\n')
        temporary.chmod(0o600)
        temporary.replace(REPORT_FILE)
    print(f'Completed: {len(failures)} failed, {len(missing)} missing', flush=True)
    return 1 if failures or missing else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='inspect backups and simulate using cached package lists')
    parser.add_argument('vmids', type=int, nargs='*', help='optional local VMIDs')
    args = parser.parse_args()
    config = json.loads(Path('/etc/lxc-auto-update.json').read_text())
    with open('/run/lock/lxc-auto-update.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another LXC update run is active')
            return 1
        return update_guests(config, args.dry_run, args.vmids)


if __name__ == '__main__':
    raise SystemExit(main())
