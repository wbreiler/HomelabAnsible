"""Build local maintenance batches from existing app adapters and exact APT plans."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time
import types

OS_CONFIG = Path('/etc/lxc-auto-update.json')
APT_SOURCE = Path(__file__).with_name('approved_apt.py')


def apt(mode, vmid=None, plan=None):
    prefix = ['pct', 'exec', str(vmid), '--'] if vmid is not None else []
    result = subprocess.run([*prefix, '/usr/bin/python3', '-c', APT_SOURCE.read_text(), mode],
                            input=json.dumps(plan) if plan is not None else None,
                            text=True, stdout=subprocess.PIPE, check=True,
                            timeout=600 if mode == 'prepare' else None)
    return json.loads(result.stdout)


def prepare(config, backend, versions, progress):
    actions, notes = [], []
    def add(label, factory):
        progress('Checking ' + label)
        try:
            result = factory()
            if result:
                actions.append(result)
            else:
                notes.append(label + ': current; no eligible changes.')
        except Exception as error:
            reason = str(error) if isinstance(error, backend.Refused) else 'Check unavailable (' + type(error).__name__ + '); excluded.'
            notes.append(label + ': ' + reason)
    def os_plan(row=None):
        vmid = row['vmid'] if row else None
        result = apt('prepare', vmid)
        label = ('CT ' + str(vmid) + ' ' + row['name']) if row else config['node']
        if result['held']:
            notes.append(label + ': held packages retained: ' + ', '.join(result['held']))
        if result['reboot_required']:
            notes.append(label + ': reboot already required; no reboot will run.')
        if result['packages']:
            return {'backend': 'apt', 'vmid': vmid, 'hostname': row['name'] if row else config['node'], 'apt': result,
                    'label': label + ': ' + str(len(result['packages'])) + ' OS/package updates',
                    'effect': 'Exact listed package versions, no removals, holds preserved. Package scripts may restart services. No reboot. ' +
                              ('A fresh PBS guest backup runs first.' if row else 'Save local host configuration first; this is not a full system image.')}
    if config['platform'] in ('pve', 'pbs'):
        if config['platform'] == 'pve':
            updater = backend.load_updater()
            settings = json.loads((backend.APP_ROOT / 'config.json').read_text())
            os_settings = json.loads(OS_CONFIG.read_text())
            guests = updater.api('/nodes/' + config['node'] + '/lxc')
            def probe_guest(row):
                try:
                    return row, apt('prepare', row['vmid']), None
                except Exception as error:
                    return row, None, type(error).__name__
            eligible = []
            for row in guests:
                if row['status'] != 'running' or row['vmid'] in os_settings['skip_vmids']:
                    notes.append('CT ' + str(row['vmid']) + ': stopped or excluded from OS maintenance.')
                else:
                    eligible.append(row)
            progress('Checking guest package plans (three guests at a time).')
            package_plans = []
            with ThreadPoolExecutor(max_workers=3) as pool:
                for row, result, error in pool.map(probe_guest, eligible):
                    if result:
                        package_plans.append((row, result))
                    label = 'CT ' + str(row['vmid']) + ' ' + row['name']
                    if error:
                        notes.append(label + ': OS check unavailable (' + error + '); excluded.')
                    elif result['packages']:
                        actions.append({'backend': 'apt', 'vmid': row['vmid'], 'hostname': row['name'], 'apt': result,
                                        'label': label + ': ' + str(len(result['packages'])) + ' OS/package updates',
                                        'effect': 'Fresh PBS guest backup, exact package versions, no removals, holds preserved. Services may restart; no reboot.'})
                    if result and result['held']:
                        notes.append(label + ': held packages retained: ' + ', '.join(result['held']))
                    if result and result['reboot_required']:
                        notes.append(label + ': reboot already required; no reboot will run.')
            def managed(row, os_result, warnings):
                if (updater.PINS / f'packages-{row["vmid"]}.failed.json').exists():
                    raise backend.Refused('Previous managed package update failed; inspect its failure brief first.')
                targets, previous = {}, {}
                for package in settings.get('packages', []):
                    if package not in os_result['held']:
                        continue
                    current = updater.guest(row['vmid'], 'dpkg-query', '-W', '-f=${Version}', package)
                    candidates = [line.split('|')[1].strip() for line in updater.guest(row['vmid'], 'apt-cache', 'madison', package).splitlines() if '|' in line]
                    target = updater.apt_candidate(current, candidates)
                    observed_path = updater.PINS / f'candidate-{row["vmid"]}-{package}.json'
                    observed = json.loads(observed_path.read_text()) if observed_path.exists() else {}
                    if target and observed.get('version') == target and time.time() - observed['first_seen'] >= settings['minimum_age_hours'] * 3600:
                        targets[package], previous[package] = target, current
                    elif target:
                        warnings.append('CT ' + str(row['vmid']) + ' ' + package + ': release-age guard not yet met; excluded.')
                if targets:
                    return {'backend': 'managed_packages', 'vmid': row['vmid'], 'hostname': row['name'],
                            'targets': targets, 'previous': previous,
                            'label': 'CT ' + str(row['vmid']) + ': ' + ', '.join(targets) + ' managed app packages',
                            'effect': 'Fresh PBS backup, existing app compatibility/age guards, exact listed versions. Temporarily update only these managed held packages, then restore their holds.',
                            'package_changes': [{'package': p, 'from': previous[p], 'to': target} for p, target in targets.items()]}
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending = []
                for row, os_result in package_plans:
                    warnings = []
                    pending.append((row, warnings, pool.submit(managed, row, os_result, warnings)))
                for row, warnings, future in pending:
                    def result():
                        try:
                            return future.result()
                        finally:
                            notes.extend(warnings)
                    add('CT ' + str(row['vmid']) + ' managed packages', result)
            names = {row['name'] for row in guests}
            with ThreadPoolExecutor(max_workers=3) as pool:
                pending = [(app, pool.submit(backend.prepare_lxc, config, app))
                           for app in dict.fromkeys(settings['roles'] + list(settings.get('native_guests', {})))
                           if updater.app_variables(app, settings)[app + '_hostname'] in names]
                for app, future in pending:
                    add(app, future.result)
            for row in updater.api('/nodes/' + config['node'] + '/qemu'):
                notes.append('VM ' + str(row['vmid']) + ': OS/app executor is not configured; excluded.')
            covered = {updater.app_variables(app, settings)[app + '_hostname'] for app in
                       settings['roles'] + list(settings.get('native_guests', {}))}
            for row in guests:
                if row['name'] not in covered:
                    notes.append('CT ' + str(row['vmid']) + ' ' + row['name'] + ': custom app installer unavailable; OS coverage is listed separately.')
        # Host packages go last, after that host's guest backups and app work.
        add(config['node'] + ' host OS', os_plan)
    elif config['platform'] == 'truenas':
        progress('Checking app images (three at a time).')
        apps = backend.nas_call('app.query')
        custom = {app['id'] for app in apps if app.get('custom_app')}
        inventory = [image for image in versions.docker_inventory() if image['app'] in custom]
        comparisons = {(image['app'], image['service']): result
                       for image, result in zip(inventory, versions.image_updates(inventory))}
        # Reuse only this preparation's observations. Execution still reads fresh state.
        snapshot = types.SimpleNamespace(docker_inventory=lambda: inventory, command=versions.command,
                                         image_update=lambda image: comparisons[(image['app'], image['service'])])
        for app in apps:
            if not app.get('custom_app'):
                notes.append(app['id'] + ': catalog app; use the TrueNAS app upgrade screen.')
                continue
            def all_images(app=app):
                if app.get('state') != 'RUNNING':
                    raise backend.Refused('App is not RUNNING; version check unavailable; excluded.')
                images = [image for image in inventory if image['app'] == app['id']]
                if not images:
                    raise backend.Refused('No running containers to compare; excluded.')
                selected = []
                unchecked = False
                for image in images:
                    result = snapshot.image_update(image)
                    if result.get('available') and not result.get('manual'):
                        selected.append(backend.prepare_nas(config, app['id'] + '/' + image['service'], snapshot))
                    elif result.get('unavailable') or result.get('manual'):
                        unchecked = True
                        notes.append(app['id'] + '/' + image['service'] + ': manual image/source check; excluded.')
                if not selected:
                    if unchecked:
                        raise backend.Refused('Some image checks unavailable or manual; excluded.')
                    return None
                merged = copy.deepcopy(selected[0])
                for plan in selected[1:]:
                    if plan['original'] != merged['original'] or plan['before_images'] != merged['before_images']:
                        raise backend.Refused('App changed during planning; excluded.')
                    service = plan['service']
                    merged['desired']['services'][service]['image'] = plan['desired']['services'][service]['image']
                    merged['expected'][service] = plan['expected'][service]
                merged['label'] = '\n'.join(plan['label'] for plan in selected)
                merged['effect'] = 'Redeploy this app once with all listed image changes. ' + merged['effect'].replace('with one new image. ', '')
                return merged
            add(app['id'], all_images)
        notes.append('TrueNAS OS: appliance upgrades require a separate maintenance/reboot plan; excluded. Never run APT on TrueNAS.')
    return {'actions': actions, 'notes': notes}


def host_health(config, backend):
    if config['platform'] == 'pve':
        updater = backend.load_updater()
        if not any(row.get('type') == 'cluster' and row.get('quorate') == 1 for row in updater.api('/cluster/status')):
            raise backend.Refused('Cluster quorum is unavailable. Host maintenance stopped.')
        tasks = updater.api('/nodes/' + config['node'] + '/tasks', '--source', 'active')
        services = ['pveproxy', 'pvedaemon', 'pve-cluster', 'corosync']
    else:
        tasks = json.loads(subprocess.check_output(['proxmox-backup-manager', 'task', 'list', '--output-format', 'json'], text=True))
        services = ['proxmox-backup', 'proxmox-backup-proxy']
    if tasks:
        raise backend.Refused('This host has active platform/backup tasks. Host maintenance stopped.')
    for service in services:
        subprocess.run(['systemctl', 'is-active', '--quiet', service], check=True)


def perform(config, action, backend, versions, progress, archive):
    if action['backend'] == 'managed_packages':
        if config['platform'] != 'pve':
            raise backend.Refused('Managed guest packages require a PVE host.')
        updater = backend.load_updater()
        settings = json.loads((backend.APP_ROOT / 'config.json').read_text())
        row = next((row for row in updater.api('/nodes/' + config['node'] + '/lxc') if row['vmid'] == action['vmid']), None)
        if not row or row['name'] != action['hostname'] or row['status'] != 'running' or not set(action['targets']) <= set(settings['packages']):
            raise backend.Refused('The managed package target changed.')
        result = updater.update_packages(row, {**settings, 'packages': list(action['targets'])}, config['node'], False, False,
                                         approved_plan={key: action[key] for key in ('previous', 'targets')})
        if result['status'] != 'updated':
            raise backend.Refused('The managed package updater did not confirm completion.')
        return 'Managed application packages updated, verified, and held again.'
    if action['backend'] != 'apt':
        return backend.perform(config, action, versions, progress)
    vmid = action['vmid']
    if config['platform'] not in ('pve', 'pbs') or (vmid is not None and config['platform'] != 'pve'):
        raise backend.Refused('Invalid OS update platform.')
    if vmid is not None:
        updater = backend.load_updater()
        settings = json.loads(OS_CONFIG.read_text())
        guests = updater.api('/nodes/' + config['node'] + '/lxc')
        row = next((row for row in guests if row['vmid'] == vmid), None)
        if not row or row['name'] != action['hostname'] or row['status'] != 'running' or vmid in settings['skip_vmids']:
            raise backend.Refused('The guest identity, state, or exclusion changed.')
        progress('Creating the fresh backup for CT ' + str(vmid))
        updater.backup(vmid, {'backup_storage': settings['backup_storage']}, config['node'])
    else:
        if action['hostname'] != config['node']:
            raise backend.Refused('The host identity changed.')
        host_health(config, backend)
        progress('Saving private host configuration before package maintenance.')
        backup = archive / 'host-configuration.tar'
        with tarfile.open(backup, 'x') as tar:
            tar.add('/etc', arcname='etc')
            tar.add('/var/lib/dpkg/status', arcname='dpkg-status')
        os.chmod(backup, 0o600)
    progress('Installing the approved package versions. No reboot will run.')
    result = apt('execute', vmid, action['apt'])
    if vmid is None:
        host_health(config, backend)
    return str(result['packages']) + ' package versions verified.' + (' Reboot required; not performed.' if result['reboot_required'] else '')
