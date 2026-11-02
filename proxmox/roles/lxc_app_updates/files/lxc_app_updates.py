#!/usr/bin/python3
"""Resolve stable releases, pin artifacts, back up, and run existing app roles."""
import argparse
from datetime import datetime, timezone
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import jinja2
import yaml


ROOT = Path(__file__).resolve().parent
STATE = Path('/var/lib/homelab-app-updates')
PINS = Path('/etc/pve/priv/homelab-app-updates')
VERSION = re.compile(r'^v?(\d+\.\d+\.\d+(?:\.\d+)?)(?:-ls(\d+))?$')
TEMPLATE = jinja2.Environment(undefined=jinja2.StrictUndefined)


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        if urllib.parse.urlsplit(url).scheme != 'https':
            raise ValueError('release download redirected away from HTTPS')
        if request.has_header('Authorization') and urllib.parse.urlsplit(url).netloc != urllib.parse.urlsplit(request.full_url).netloc:
            raise ValueError('refusing to forward registry credentials to another host')
        return super().redirect_request(request, fp, code, message, headers, url)


OPENER = urllib.request.build_opener(HTTPSRedirect())


def run(args, **kwargs):
    kwargs.setdefault('timeout', 300)
    return subprocess.check_output(args, text=True, **kwargs).strip()


def guest(vmid, *args):
    return run(['pct', 'exec', str(vmid), '--', *args])


def api(path, *args):
    return json.loads(run(['pvesh', 'get', path, *args, '--output-format', 'json']))


def fetch(url, headers=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password:
        raise ValueError('release metadata and artifacts must use HTTPS without credentials')
    request = urllib.request.Request(url, headers={'User-Agent': 'HomelabAnsible-app-updates', **(headers or {})})
    return OPENER.open(request, timeout=90)


def json_url(url):
    with fetch(url) as response:
        return json.load(response)


def version(value):
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError('unsupported or prerelease version')
    return tuple(map(int, match[1].split('.'))) + ((int(match[2]),) if match[2] else ())


def compatible(current, target):
    old, new = version(current), version(target)
    # SemVer 0.x can introduce breaking changes at every minor release.
    width = 2 if old[0] == 0 else 1
    return new[:width] == old[:width] and new > old


def choose_release(releases, current, minimum_age_hours, now):
    candidates = []
    for release in releases:
        if release.get('draft') or release.get('prerelease'):
            continue
        try:
            tag = release['tag_name']
            published = datetime.fromisoformat(release['published_at'].replace('Z', '+00:00')).timestamp()
            if compatible(current, tag) and now - published >= minimum_age_hours * 3600:
                candidates.append(release)
        except (KeyError, ValueError, TypeError):
            continue
    return max(candidates, key=lambda row: version(row['tag_name']), default=None)


def artifact_checksum(url, expected=None):
    digest = hashlib.sha256()
    with fetch(url) as response:
        if urllib.parse.urlsplit(response.url).scheme != 'https':
            raise ValueError('artifact redirected away from HTTPS')
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
    actual = 'sha256:' + digest.hexdigest()
    if expected and actual != expected:
        raise ValueError('upstream artifact checksum mismatch')
    return actual


def image_digest(image, tag):
    registry, repository = image.split('/', 1)
    if registry != 'ghcr.io':
        raise ValueError('unsupported image registry')
    token = json_url(f'https://ghcr.io/token?service=ghcr.io&scope=repository:{repository}:pull')['token']
    with fetch(f'https://ghcr.io/v2/{repository}/manifests/{tag}', {
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json',
    }) as response:
        content = response.read()
        digest = 'sha256:' + hashlib.sha256(content).hexdigest()
        if response.headers.get('Docker-Content-Digest') != digest:
            raise ValueError('registry manifest checksum mismatch')
        return digest


def app_variables(app, config):
    if app in config.get('native_guests', {}):
        return {app + '_hostname': config['native_guests'][app]}
    values = yaml.safe_load((ROOT / 'roles' / app / 'defaults/main.yml').read_text())
    values.update(config['variables'])
    if (PINS / f'{app}.json').exists():
        values.update(json.loads((PINS / f'{app}.json').read_text()))
    return values


def current_version(app, spec, vmid):
    if app == 'netboot_xyz':
        try:
            return guest(vmid, 'cat', '/etc/netboot-xyz-version')
        except subprocess.CalledProcessError:
            installed = guest(vmid, 'sha256sum', '/srv/tftp/netboot.xyz.efi').split()[0]
            releases = json_url('https://api.github.com/repos/netbootxyz/netboot.xyz/releases?per_page=100')
            for release in releases:
                if any(a.get('name') == 'netboot.xyz.efi' and a.get('digest') == 'sha256:' + installed for a in release.get('assets', [])):
                    return release['tag_name'].removeprefix('v')
            raise ValueError('cannot identify the installed netboot.xyz artifact')
    if 'image' in spec:
        images = guest(vmid, 'docker', 'compose', '--project-directory', spec['compose'], 'config', '--images').splitlines()
        ref = next(image for image in images if image.startswith(spec['image'] + ':'))
        return ref.split(':', 1)[1].split('@', 1)[0]
    if app in ('sonarr', 'radarr'):
        # Keep API keys inside the guest and out of both argv and output.
        code = '''import json,sys,urllib.request,xml.etree.ElementTree as ET
c=ET.parse('/var/lib/'+sys.argv[1]+'/config.xml').getroot()
r=urllib.request.Request('http://127.0.0.1:'+c.findtext('Port')+'/api/v3/system/status',headers={'X-Api-Key':c.findtext('ApiKey')})
print(json.load(urllib.request.urlopen(r,timeout=15))['version'])'''
        output = guest(vmid, 'python3', '-c', code, app)
    else:
        output = guest(vmid, 'sh', '-c', spec['probe'])
    if 'package' in spec:
        return output
    matches = re.findall(r'(?<![\d.])\d+\.\d+\.\d+(?:\.\d+)?(?![\d.])', output)
    if not matches:
        raise ValueError('cannot establish installed application version')
    return matches[0]


def resolve_pins(app, spec, values, release):
    target = release['tag_name'].removeprefix('v')
    if 'image' in spec:
        tag = release['tag_name'] if app == 'speedtest_tracker' else target
        return {app + '_image': f'{spec["image"]}:{tag}@{image_digest(spec["image"], tag)}'}
    if spec.get('native'):
        if app == 'open_webui':
            wheels = json_url(f'https://pypi.org/pypi/open-webui/{target}/json')['urls']
            wheel = next(w for w in wheels if w['filename'].endswith('-py3-none-any.whl') and not w.get('yanked'))
            artifacts = [{'name': wheel['filename'], 'url': wheel['url'], 'checksum': 'sha256:' + wheel['digests']['sha256']}]
        elif app in ('sabnzbd', 'netboot_xyz'):
            names = [f'SABnzbd-{target}-src.tar.gz'] if app == 'sabnzbd' else ['netboot.xyz.efi', 'netboot.xyz.kpxe']
            artifacts = []
            for name in names:
                asset = next(a for a in release['assets'] if a['name'] == name)
                url = asset['browser_download_url']
                artifacts.append({'name': name, 'url': url, 'checksum': artifact_checksum(url, asset.get('digest'))})
        else:
            url = f'https://api.github.com/repos/{spec["repository"]}/tarball/{release["tag_name"]}'
            artifacts = [{'name': app + '.tar.gz', 'url': url, 'checksum': artifact_checksum(url)}]
        pins = {app + '_version': target, 'artifacts': artifacts}
        if app == 'homelable':
            pins.update(homelable_release_url=artifacts[0]['url'], homelable_release_checksum=artifacts[0]['checksum'])
        return pins
    prefix = app + '_' + spec.get('artifact', 'release')
    values = {**values, app + '_version': target}
    # Saved pins contain literal URLs for earlier releases. Resolve new releases
    # from the repository-owned URL template, never from those historical pins.
    defaults = yaml.safe_load((ROOT / 'roles' / app / 'defaults/main.yml').read_text())
    url = TEMPLATE.from_string(defaults[prefix + '_url']).render(values)
    asset = next((a for a in release.get('assets', []) if a.get('browser_download_url') == url), {})
    pins = {app + '_version': target, prefix + '_url': url,
            prefix + '_checksum': artifact_checksum(url, asset.get('digest'))}
    if app == 'vaultwarden':
        base = f'https://raw.githubusercontent.com/dani-garcia/vaultwarden/{release["tag_name"]}/'
        with fetch(base + 'docker/DockerSettings.yaml') as response:
            web_version = yaml.safe_load(response)['vault_version'].removeprefix('v')
        version(web_version)
        web_url = f'https://github.com/dani-garcia/bw_web_builds/releases/download/v{web_version}/bw_web_v{web_version}.tar.gz'
        pins.update(vaultwarden_web_version=web_version, vaultwarden_web_url=web_url,
                    vaultwarden_web_checksum=artifact_checksum(web_url))
        with fetch(base + 'rust-toolchain.toml') as response:
            import tomllib
            rust = tomllib.loads(response.read().decode())['toolchain']['channel']
        version(rust)
        pins['vaultwarden_rust_version'] = rust
    return pins


def save_json(path, content):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(content, indent=2) + '\n')
    os.replace(temporary, path)


def apt_version(value):
    match = re.fullmatch(r'(?:\d+:)?(\d+\.\d+\.\d+)(?:[-+~][0-9A-Za-z.+:~_-]+)?', value)
    if not match or re.search(r'(alpha|beta|rc|dev)', value, re.I):
        raise ValueError('unsupported or prerelease package version')
    return version(match[1])


def apt_candidate(current, candidates):
    old = apt_version(current)
    eligible = []
    for candidate in candidates:
        try:
            new = apt_version(candidate)
        except ValueError:
            continue
        width = 2 if old[0] == 0 else 1
        if old[:width] == new[:width] and subprocess.run(['dpkg', '--compare-versions', candidate, 'gt', current]).returncode == 0:
            eligible.append(candidate)
    def compare(a, b):
        return 1 if subprocess.run(['dpkg', '--compare-versions', a, 'gt', b]).returncode == 0 else -1
    return max(eligible, key=functools.cmp_to_key(compare), default=None)


def package_ready(vmid, package, target, config):
    # Signed APT indexes do not provide per-package release dates.
    path = PINS / f'candidate-{vmid}-{package}.json'
    observed = json.loads(path.read_text()) if path.exists() else {}
    if observed.get('version') != target:
        observed = {'version': target, 'first_seen': time.time()}
        save_json(path, observed)
    ready = time.time() - observed['first_seen'] >= config['minimum_age_hours'] * 3600
    if not ready:
        print(f'WAIT {vmid} {package} {target}: stable candidate age gate', flush=True)
    return ready


def backup(vmid, config, node):
    if api(f'/nodes/{node}/lxc/{vmid}/status/current')['status'] != 'running':
        raise RuntimeError('guest moved or stopped')
    if api(f'/nodes/{node}/lxc/{vmid}/config').get('lock'):
        raise RuntimeError('guest is locked for another operation')
    # vzdump's unprivileged backup client must traverse its temporary metadata.
    subprocess.run(['vzdump', str(vmid), '--storage', config['backup_storage'], '--mode', 'snapshot', '--compress', 'zstd'],
                   check=True, umask=0o022)


def install_native(app, target, pins, vmid):
    cache = '/var/cache/homelab-app-updates/' + app + '/' + target
    guest(vmid, 'install', '-d', '-m', '0700', cache)
    for artifact in pins['artifacts']:
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+', artifact['name']):
            raise ValueError('invalid artifact filename')
        with tempfile.NamedTemporaryFile(dir=STATE) as downloaded:
            digest = hashlib.sha256()
            with fetch(artifact['url']) as response:
                while chunk := response.read(1024 * 1024):
                    downloaded.write(chunk)
                    digest.update(chunk)
            if 'sha256:' + digest.hexdigest() != artifact['checksum']:
                raise ValueError('artifact changed after release resolution')
            downloaded.flush()
            subprocess.run(['pct', 'push', str(vmid), downloaded.name, cache + '/' + artifact['name'], '--perms', '0600'], check=True)
    subprocess.run(['pct', 'push', str(vmid), str(ROOT / 'native_apps.py'), '/root/homelab-native-app-update.py', '--perms', '0700'], check=True)
    subprocess.run(['pct', 'exec', str(vmid), '--', 'python3', '/root/homelab-native-app-update.py', app, target,
                    cache + '/' + pins['artifacts'][0]['name']], check=True, umask=0o022)
    if app == 'homelable':
        subprocess.run(['pct', 'exec', str(vmid), '--', '/opt/homelable/venv/bin/python', '-', '3000'],
                       input=(ROOT / 'roles/homelable/files/verify.py').read_text(), text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)


def update_packages(row, config, node, dry_run, retry_failed):
    vmid = row['vmid']
    failure = PINS / f'packages-{vmid}.failed.json'
    if failure.exists() and not retry_failed:
        raise RuntimeError('previous package update failed; inspect before --retry-failed')
    changes = {}
    for package in config.get('packages', []):
        try:
            current = run(['pct', 'exec', str(vmid), '--', 'dpkg-query', '-W', '-f=${Version}', package], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        if not current:
            continue
        candidates = [line.split('|')[1].strip() for line in guest(vmid, 'apt-cache', 'madison', package).splitlines() if '|' in line]
        target = apt_candidate(current, candidates)
        if target and package_ready(vmid, package, target, config):
            changes[package] = target
            print(f'{"PLAN" if dry_run else "UPDATE"} {vmid} {package}: {current} -> {target}', flush=True)
    if not changes or dry_run:
        return {'app': 'packages', 'vmid': vmid, 'status': 'planned' if changes else 'current', 'targets': changes}
    backup(vmid, config, node)
    try:
        before = guest(vmid, 'systemctl', '--failed', '--plain', '--no-legend', '--no-pager')
        subprocess.run(['pct', 'exec', str(vmid), '--', 'env', 'DEBIAN_FRONTEND=noninteractive', 'NEEDRESTART_MODE=a',
                        'apt-get', '-o', 'DPkg::Lock::Timeout=300', '--no-remove', '--allow-change-held-packages',
                        '-y', 'install', *[p + '=' + v for p, v in changes.items()]], check=True, umask=0o022)
        guest(vmid, 'apt-mark', 'hold', *changes)
        for package, target in changes.items():
            if guest(vmid, 'dpkg-query', '-W', '-f=${Version}', package) != target:
                raise RuntimeError('installed package does not match selected version')
            guest(vmid, 'systemctl', 'is-active', '--quiet', {'grafana': 'grafana-server', 'tailscale': 'tailscaled'}.get(package, package))
        after = guest(vmid, 'systemctl', '--failed', '--plain', '--no-legend', '--no-pager')
        if set(after.splitlines()) - set(before.splitlines()):
            raise RuntimeError('new failed units after package updates')
    except Exception:
        save_json(failure, {'targets': changes, 'time': time.time()})
        raise
    for package, target in changes.items():
        role, key = ('tailscale_router', 'tailscale_router_version') if package == 'tailscale' else ('centralized_logging', 'centralized_logging_' + package + '_version')
        save_json(PINS / f'{role}-{package}.json', {key: target})
    failure.unlink(missing_ok=True)
    return {'app': 'packages', 'vmid': vmid, 'status': 'updated', 'targets': changes}


def update_one(app, spec, row, config, node, dry_run, retry_failed=False):
    vmid = row['vmid']
    failure = PINS / f'{app}-{vmid}.failed.json'
    if failure.exists() and not retry_failed:
        raise RuntimeError('previous deployment failed; inspect the log before --retry-failed')
    current = current_version(app, spec, vmid)
    if 'package' in spec:
        versions = guest(vmid, 'apt-cache', 'madison', spec['package']).splitlines()
        candidates = [line.split('|')[1].strip() for line in versions if '|' in line]
        target = apt_candidate(current, candidates)
        if target and not package_ready(vmid, spec['package'], target, config):
            target = None
        pins = {app + '_version': target} if target else None
    else:
        endpoint = spec.get('api', 'https://api.github.com')
        releases = json_url(f'{endpoint}/repos/{spec["repository"]}/releases?per_page=100&limit=100')
        release = choose_release(releases, current, config['minimum_age_hours'], time.time())
        target = release['tag_name'].removeprefix('v') if release else None
        pins = resolve_pins(app, spec, app_variables(app, config), release) if release else None
    if not pins:
        if failure.exists():
            raise RuntimeError('failed deployment has no newer candidate; repair and verify health before removing its failure marker')
        print(f'CURRENT {vmid} {app} {current}: no eligible stable update', flush=True)
        return {'app': app, 'vmid': vmid, 'current': current, 'status': 'current'}
    print(f'{"PLAN" if dry_run else "UPDATE"} {vmid} {app}: {current} -> {target}', flush=True)
    if dry_run:
        return {'app': app, 'vmid': vmid, 'current': current, 'target': target, 'status': 'planned'}
    backup(vmid, config, node)
    before = guest(vmid, 'systemctl', '--failed', '--plain', '--no-legend', '--no-pager')
    variables = {**config['variables'], **pins, 'update_role': app,
                 'lxc_app_updates_backup_complete': True, 'lxc_manage_ssh_key': False,
                 'lxc_app_updates_running': True, 'zipline_manage_proxy': False}
    try:
        if spec.get('native'):
            install_native(app, target, pins, vmid)
        else:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=STATE) as var_file:
                json.dump(variables, var_file)
                var_file.flush()
                subprocess.run(['ansible-playbook', '-i', node + ',', 'run.yml', '-e', '@' + var_file.name],
                               cwd=ROOT, check=True, umask=0o022)
        installed = current_version(app, spec, vmid)
        matches = installed == target if 'package' in spec else version(installed) == version(target)
        if not matches:
            raise RuntimeError('installed version does not match the selected release')
        after = guest(vmid, 'systemctl', '--failed', '--plain', '--no-legend', '--no-pager')
        if set(after.splitlines()) - set(before.splitlines()):
            raise RuntimeError('new failed guest units after application update')
        save_json(PINS / f'{app}.json', pins)
        if app == 'librespeed':
            pin = pins['artifacts'][0]
            subprocess.run(['pct', 'exec', str(vmid), '--', 'sh', '-c', 'umask 077; cat > /etc/librespeed-auto-update.json'],
                           input=json.dumps({'librespeed_version': target, 'librespeed_release_url': pin['url'], 'librespeed_release_checksum': pin['checksum']}), text=True, check=True)
    except Exception:
        save_json(failure, {'app': app, 'vmid': vmid, 'from': current, 'target': target, 'time': time.time()})
        raise
    failure.unlink(missing_ok=True)
    print(f'OK {vmid} {app} {target}', flush=True)
    return {'app': app, 'vmid': vmid, 'current': target, 'status': 'updated'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('apps', nargs='*', help='optional catalog application names')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config.json').read_text())
    catalog = yaml.safe_load((ROOT / 'catalog.yml').read_text())
    unknown = set(args.apps) - (catalog.keys() | {'packages'})
    if unknown:
        parser.error('unknown applications: ' + ', '.join(sorted(unknown)))
    node = socket.gethostname().split('.')[0]
    os.umask(0o077)
    # The OS updater uses the same lock, so the two jobs cannot overlap.
    with open('/run/lock/lxc-auto-update.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        guests = {row['name']: row for row in api(f'/nodes/{node}/lxc') if row['status'] == 'running'}
        report = []
        for app in config['roles'] + list(config.get('native_guests', {})):
            if (args.apps and app not in args.apps) or app in config['exclude']:
                continue
            values = app_variables(app, config)
            row = guests.get(values[app + '_hostname'])
            if row is None:
                continue
            try:
                report.append(update_one(app, catalog[app], row, config, node, args.dry_run, args.retry_failed))
            except Exception as error:
                # Command exception strings can contain credential-bearing arguments.
                detail = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
                print(f'FAILED {row["vmid"]} {app}: {detail}', flush=True)
                report.append({'app': app, 'vmid': row['vmid'], 'status': 'failed', 'reason': detail})
        if not args.apps or 'packages' in args.apps:
            for row in guests.values():
                try:
                    report.append(update_packages(row, config, node, args.dry_run, args.retry_failed))
                except Exception as error:
                    detail = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
                    print(f'FAILED {row["vmid"]} packages: {detail}', flush=True)
                    report.append({'app': 'packages', 'vmid': row['vmid'], 'status': 'failed', 'reason': detail})
        save_json(STATE / ('plan.json' if args.dry_run else 'last-run.json'),
                  report if args.dry_run else {'invocation_id': os.environ.get('INVOCATION_ID'), 'results': report})
        return int(any(row['status'] == 'failed' for row in report))


if __name__ == '__main__':
    raise SystemExit(main())
