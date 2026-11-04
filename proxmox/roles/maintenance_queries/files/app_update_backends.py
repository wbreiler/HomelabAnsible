"""Fixed, single-app adapters. No user or model supplied commands."""
import copy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

APP_ROOT = Path('/opt/homelab-app-updates')
BACKUP_ROOT = Path('/mnt/gaia/appdata/_cloud-backup')


class Refused(ValueError):
    """A fixed, public explanation that is safe for Discord."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_updater():
    sys.path.insert(0, str(APP_ROOT))
    spec = importlib.util.spec_from_file_location('approved_app_updater', APP_ROOT / 'lxc_app_updates.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lxc_context(config, name):
    updater = load_updater()
    settings = json.loads((APP_ROOT / 'config.json').read_text())
    catalog = updater.yaml.safe_load((APP_ROOT / 'catalog.yml').read_text())
    choices = list(dict.fromkeys(settings['roles'] + list(settings.get('native_guests', {}))))
    matches = [app for app in choices if app.replace('_', '-') == name.replace('_', '-')]
    if len(matches) != 1 or matches[0] in settings['exclude']:
        raise Refused('This app has no enabled guarded installer here. Use its managed playbook. No update started.')
    app = matches[0]
    hostname = updater.app_variables(app, settings)[app + '_hostname']
    guests = updater.api('/nodes/' + config['node'] + '/lxc')
    matches = [row for row in guests if row.get('name') == hostname]
    if len(matches) != 1 or matches[0]['status'] != 'running':
        raise Refused('The app is not a unique running guest on this host. Check its current host.')
    row = matches[0]
    if updater.api(f'/nodes/{config["node"]}/lxc/{row["vmid"]}/config').get('lock'):
        raise Refused('The guest is locked by another operation. Try after it finishes.')
    if (updater.PINS / f'{app}-{row["vmid"]}.failed.json').exists():
        raise Refused('A previous app update failed. Use the failure brief repair approval first.')
    # The old netboot adapter cannot safely identify installations with the Secure Boot shim.
    if app == 'netboot_xyz':
        raise Refused('Netboot requires its dedicated playbook to preserve the Secure Boot loader.')
    return updater, settings, catalog[app], app, row


def prepare_lxc(config, name):
    updater, settings, spec, app, row = lxc_context(config, name)
    resolved = updater.resolve_update(app, spec, row, settings, observe=False)
    if not resolved['pins']:
        raise Refused('No compatible stable update passes the existing release-age guard yet. No update started.')
    return {'backend': 'lxc', 'app': app, 'vmid': row['vmid'], 'hostname': row['name'], 'resolved': resolved,
            'label': f'{app} · CT {row["vmid"]}: {resolved["current"]} → {resolved["target"]}',
            'effect': 'Create a fresh PBS backup, then update this app and its managed dependencies. The app may restart. Existing age, checksum, compatibility, and health guards apply.'}


def backup_receipt():
    path = BACKUP_ROOT / 'last-run.json'
    if not path.exists():
        raise Refused('The TrueNAS backup receipt is missing. Complete the nightly backup before an app update.')
    receipt = json.loads(path.read_text())
    age = time.time() - datetime.fromisoformat(receipt['finished']).timestamp()
    if (receipt.get('passed') is not True or not 0 <= age <= 30 * 3600 or
            not {'system-config', 'app-settings', 'appdata'} <= set(receipt.get('completed', []))):
        raise Refused('TrueNAS needs a successful appdata, settings, and system backup within 30 hours.')
    return receipt['finished']


def nas_call(method, *args, job=False):
    from truenas_api_client import Client
    with Client() as client:
        return client.call(method, *args, job=job, timeout=None if job else 60)


def same_release_line(current, target):
    def number(value):
        match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?', value)
        if not match or re.search(r'(?i)(alpha|beta|rc(?:[0-9._-]|$)|pre(?:view)?(?:[0-9._-]|$)|nightly|dev)', value):
            raise Refused('The image version is not a stable numbered release. Use its managed playbook.')
        return tuple(int(part or 0) for part in match.groups())
    old, new = number(current), number(target)
    width = 2 if old[0] == 0 else 1
    if old[:width] != new[:width] or new < old:
        raise Refused('This is a major, incompatible, or older release. It needs a manual upgrade plan.')


def prepare_nas(config, name, versions):
    app, _, requested_service = name.partition('/')
    row = nas_call('app.get_instance', app)
    if row.get('state') != 'RUNNING' or not row.get('custom_app'):
        raise Refused('This adapter needs a running custom app. Catalog apps use the TrueNAS app upgrade screen.')
    original = nas_call('app.config', app)
    services = original.get('services', {})
    images = [image for image in versions.docker_inventory() if image['app'] == app]
    by_service = {image['service']: image for image in images}
    if (not services or len(images) != len(by_service) or set(services) != set(by_service) or
            any(service.get('build') or service.get('profiles') for service in services.values())):
        raise Refused('This app has inactive, replicated, or build-only services. Use its managed playbook.')
    desired = copy.deepcopy(original)
    expected = {}
    candidates = []
    for service, values in services.items():
        image = by_service[service]
        if values.get('image') != image['ref'] or not image['digests']:
            raise Refused('An image is locally built or differs from its configuration. Use its managed playbook.')
        # app.update redeploys the whole Compose project. Pin unchanged sidecars to their current image.
        pinned = next((ref for ref in image['digests'] if re.fullmatch(r'[A-Za-z0-9._/:\-]+@sha256:[0-9a-f]{64}', ref)), None)
        if pinned is None:
            raise Refused('An installed image has no verified repository digest.')
        desired['services'][service]['image'] = image['ref'].split('@', 1)[0] + '@' + pinned.rsplit('@', 1)[1]
        expected[service] = image['image_id']
        if not requested_service or service == requested_service:
            result = versions.image_update(image)
            if result.get('unavailable') or result.get('comparison_uncertain') or result.get('manual'):
                raise Refused('The image comparison is incomplete. Resolve the version check before an update.')
            if result.get('available'):
                candidates.append((service, image, result))
    if not candidates:
        raise Refused('No verified image update exists for that app/service. No update started.')
    if len(candidates) != 1:
        raise Refused('Several images can update. Request one app/service from the version report, for example deluge/gluetun.')
    service, image, result = candidates[0]
    same_release_line(result['current'], result['latest'])
    target = result['checked_image']
    manifest = json.loads(versions.command(['docker', 'buildx', 'imagetools', 'inspect', target, '--format', '{{json .Manifest}}']))
    descriptor = manifest
    if 'manifests' in manifest:
        descriptor = next(entry for entry in manifest['manifests'] if entry.get('platform', {}).get('os') == image['os'] and
                          entry['platform'].get('architecture') == image['arch'] and
                          (not image.get('variant') or entry['platform'].get('variant') == image['variant']))
    checksum = descriptor['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', checksum) or checksum != result['target_digest']:
        raise Refused('The upstream image changed during inspection. Request a fresh proposal.')
    pinned = target + '@' + checksum
    raw = json.loads(versions.command(['docker', 'buildx', 'imagetools', 'inspect', pinned, '--raw']))
    expected[service] = raw['config']['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected[service]):
        raise Refused('The target image identity is invalid.')
    desired['services'][service]['image'] = pinned
    finished = backup_receipt()
    return {'backend': 'truenas', 'app': app, 'service': service, 'original': original, 'desired': desired,
            'before_images': {key: image['image_id'] for key, image in by_service.items()}, 'expected': expected,
            'label': f'{app}/{service}: {result["current"]} → {result["latest"]}',
            'effect': f'Redeploy this app, including its sidecars, with one new image. Other images stay pinned. Backup completed {finished}. Recovery may lose changes since that backup. No automatic rollback.'}


def prepare(config, name, versions):
    if config['platform'] == 'pve':
        return prepare_lxc(config, name)
    if config['platform'] == 'truenas':
        return prepare_nas(config, name, versions)
    raise Refused('PBS application maintenance uses host package updates. This command only updates guest/custom apps.')


def perform(config, plan, versions, progress):
    if plan['backend'] == 'lxc' and config['platform'] == 'pve':
        updater, settings, spec, app, row = lxc_context(config, plan['app'])
        if row['vmid'] != plan['vmid'] or row['name'] != plan['hostname']:
            raise Refused('The guest identity changed. No update started.')
        progress('Backup and guarded app update in progress. Large builds can take 30 minutes or more.')
        result = updater.update_one(app, spec, row, settings, config['node'], False, approved_plan=plan['resolved'])
        if result['status'] != 'updated':
            raise Refused('The guarded updater did not confirm an update. Inspect its private log.')
        return 'Updated to ' + str(result['current']) + '. Existing updater verification passed.'
    if plan['backend'] != 'truenas' or config['platform'] != 'truenas':
        raise Refused('The update backend changed. Request a fresh proposal.')
    backup_receipt()
    if nas_call('app.config', plan['app']) != plan['original']:
        raise Refused('The app configuration changed after the proposal. No update started.')
    row = nas_call('app.get_instance', plan['app'])
    images = [image for image in versions.docker_inventory() if image['app'] == plan['app']]
    if row['state'] != 'RUNNING' or {image['service']: image['image_id'] for image in images} != plan['before_images']:
        raise Refused('The running app changed after the proposal. No update started.')
    if plan['app'] == 'tdarr':
        for image in images:
            processes = versions.command(['docker', 'top', image['container'], '-eo', 'comm']).splitlines()
            if any(name.strip() in ('ffmpeg', 'HandBrakeCLI') for name in processes):
                raise Refused('Tdarr is transcoding. Wait for the work to finish, then request a new proposal.')
    progress('Redeploying the approved image. This app and its sidecars may restart.')
    nas_call('app.update', plan['app'], {'custom_compose_config': plan['desired']}, job=True)
    progress('Verifying app state, image identities, and container health.')
    for _ in range(60):
        images = [image for image in versions.docker_inventory() if image['app'] == plan['app']]
        healthy = {image['service']: image['image_id'] for image in images} == plan['expected']
        for image in images:
            state = json.loads(versions.command(['docker', 'inspect', '--format', '{{json .State}}', image['container']]))
            healthy = healthy and state.get('Running') is True and state.get('Health', {}).get('Status', 'healthy') == 'healthy'
        if healthy and nas_call('app.get_instance', plan['app'])['state'] == 'RUNNING':
            if nas_call('app.config', plan['app']) != plan['desired']:
                raise Refused('The resulting configuration differs from the approved configuration. Inspect the app before any further action.')
            return 'Updated. Exact images, app state, and available container health checks passed. Full user workflows were not tested.'
        time.sleep(3)
    raise Refused('The update did not pass runtime verification within three minutes. Inspect the app. No automatic retry or rollback.')
