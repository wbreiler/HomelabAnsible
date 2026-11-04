#!/usr/bin/python3
"""Resolve and execute one exact APT transaction, preserving holds and packages."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PACKAGE = re.compile(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?')
VERSION = re.compile(r'[0-9A-Za-z.+:~_-]+')


def read(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=300).strip()


def transaction(output):
    changes = []
    for line in output.splitlines():
        if line.startswith('Remv '):
            raise ValueError('Package removals are forbidden')
        if not line.startswith('Inst '):
            continue
        match = re.match(r'Inst (\S+)(?: \[([^\]]+)\])? \((\S+) ', line)
        if not match or not PACKAGE.fullmatch(match[1]) or not VERSION.fullmatch(match[3]):
            raise ValueError('Unrecognized package transaction')
        changes.append({'package': match[1], 'from': match[2], 'to': match[3]})
    if len(changes) > 2000 or len({row['package'] for row in changes}) != len(changes):
        raise ValueError('Invalid package count')
    return sorted(changes, key=lambda row: row['package'])


def installed():
    result = {}
    for line in read(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n']).splitlines():
        name, version, state = line.split('\t')
        if state == 'installed':
            result[name] = version
    return result


def lookup(versions, package):
    if package in versions:
        return versions[package]
    matches = [value for name, value in versions.items() if name.split(':')[0] == package]
    if len(matches) > 1:
        raise ValueError('Ambiguous package architecture')
    return matches[0] if matches else None


def qualified(package, architecture):
    return package if ':' in package else package + ':' + architecture


def before():
    if not Path('/run/systemd/system').is_dir() or read(['dpkg', '--audit']):
        raise ValueError('A healthy systemd/APT installation is required')
    return {'held': sorted(read(['apt-mark', 'showhold']).splitlines()),
            'failed': sorted(read(['systemctl', '--failed', '--no-legend', '--plain', '--no-pager']).splitlines())}


def prepare():
    baseline = before()
    read(['apt-get', '-o', 'DPkg::Lock::Timeout=60', '-o', 'APT::Update::Error-Mode=any', 'update'])
    changes = transaction(read(['apt-get', '--simulate', '--with-new-pkgs', '--no-remove', 'upgrade']))
    return {**baseline, 'packages': changes, 'reboot_required': Path('/var/run/reboot-required').exists()}


def execute(plan):
    baseline = before()
    if baseline['held'] != plan['held'] or set(baseline['failed']) - set(plan['failed']):
        raise ValueError('Package holds or service health changed after approval')
    changes = plan['packages']
    if not changes or len(changes) > 2000:
        raise ValueError('Empty or oversized transaction')
    versions = installed()
    architecture = read(['dpkg', '--print-architecture'])
    automatic = {qualified(package, architecture) for package in read(['apt-mark', 'showauto']).splitlines()}
    for row in changes:
        if (set(row) != {'package', 'from', 'to'} or not PACKAGE.fullmatch(row['package']) or
                not VERSION.fullmatch(row['to']) or row['package'].split(':')[0] in {p.split(':')[0] for p in plan['held']}):
            raise ValueError('Invalid or held package target')
        current = lookup(versions, row['package'])
        if current != row['from']:
            raise ValueError('Installed package version changed after approval')
    targets = [row['package'] + '=' + row['to'] for row in changes]
    if transaction(read(['apt-get', '--simulate', '--no-remove', 'install', *targets])) != changes:
        raise ValueError('APT now proposes different dependencies or versions')
    # Never time out dpkg. APT retains signature checks and rejects held-package changes.
    subprocess.run(['apt-get', '-o', 'DPkg::Lock::Timeout=300', '-o', 'Dpkg::Options::=--force-confdef',
                    '-o', 'Dpkg::Options::=--force-confold', '--no-remove', '-y', 'install', *targets],
                   check=True, stdout=sys.stderr, stderr=sys.stderr,
                   env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive', 'APT_LISTCHANGES_FRONTEND': 'none',
                        'NEEDRESTART_MODE': 'l'}, umask=0o022)
    actual = installed()
    if any(lookup(actual, row['package']) != row['to'] for row in changes):
        raise ValueError('Installed packages do not match the approved versions')
    restore_auto = [row['package'] for row in changes if row['from'] is None or
                    qualified(row['package'], architecture) in automatic]
    if restore_auto:
        read(['apt-mark', 'auto', *restore_auto])
    after = before()
    if after['held'] != plan['held'] or set(after['failed']) - set(baseline['failed']):
        raise ValueError('New failed services or changed package holds after maintenance')
    return {'packages': len(changes), 'reboot_required': Path('/var/run/reboot-required').exists()}


if __name__ == '__main__':
    os.environ['LC_ALL'] = 'C'
    mode = sys.argv[1]
    if mode not in ('prepare', 'execute'):
        raise SystemExit('Unsupported mode')
    print(json.dumps(prepare() if mode == 'prepare' else execute(json.load(sys.stdin))))
