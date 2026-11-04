"""Read installed app identities and upstream metadata without deploying anything."""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def command(args, timeout=45):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=timeout).strip()


def text(value, limit=120):
    return re.sub(r'[^A-Za-z0-9 ._+:/()\[\]-]', '', str(value))[:limit]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Redirect refused')


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'HomelabAnsible-version-check', **(headers or {})})
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(req, timeout=30) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Metadata exceeds limit')
    return json.loads(data)


@lru_cache(maxsize=150)
def public_json(url):
    return fetch(url)


def error_reason(error):
    if isinstance(error, urllib.error.HTTPError):
        return 'Upstream HTTP ' + str(error.code)
    if isinstance(error, subprocess.TimeoutExpired):
        return 'Version probe timed out'
    return 'Version probe failed (' + type(error).__name__ + ')'


def pack_config():
    path = Path('/etc/minecraft/update.conf')
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.fullmatch(r'([A-Z_]+)=(.*)', line)
            if match:
                values = shlex.split(match[2], comments=True)
                if len(values) == 1:
                    result[match[1]] = values[0]
    return result


def docker_inventory(run=command):
    rows = []
    ids = [cid for cid in run(['docker', 'ps', '-q']).split()[:50] if re.fullmatch(r'[0-9a-f]{12,64}', cid)]
    if not ids:
        return rows
    # Inspect selected fields in bulk; full Docker objects can contain credentials.
    fmt = '[{{json .Id}},{{json .Config.Image}},{{json .Image}},{{json .Name}},{{with (index .Config "Labels")}}{{json (index . "com.docker.compose.project")}}{{else}}null{{end}},{{with (index .Config "Labels")}}{{json (index . "com.docker.compose.service")}}{{else}}null{{end}}]'
    containers = [json.loads(line) for line in run(['docker', 'container', 'inspect', '--format', fmt, *ids]).splitlines()]
    image_ids = list(dict.fromkeys(row[2] for row in containers))
    if len(containers) != len(ids) or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', value) for value in image_ids):
        raise ValueError('Incomplete Docker inventory')
    fmt = '[{{json .Id}},{{json .RepoDigests}},{{json .Os}},{{json .Architecture}},{{json (index . "Variant")}},{{with (index .Config "Labels")}}{{json (index . "org.opencontainers.image.version")}}{{else}}null{{end}},{{with (index .Config "Labels")}}{{json (index . "org.opencontainers.image.source")}}{{else}}null{{end}},{{with (index .Config "Labels")}}{{json (index . "org.opencontainers.image.revision")}}{{else}}null{{end}}]'
    images = [json.loads(line) for line in run(['docker', 'image', 'inspect', '--format', fmt, *image_ids]).splitlines()]
    by_image = {row[0]: row[1:] for row in images}
    if len(images) != len(image_ids) or set(by_image) != set(image_ids):
        raise ValueError('Incomplete Docker image inventory')
    for cid in ids:
        matches = [row for row in containers if row[0].startswith(cid)]
        if len(matches) != 1:
            raise ValueError('Ambiguous Docker container identity')
        _, ref, image_id, name, project, service = matches[0]
        digests, os_name, arch, variant, version, source, revision = by_image[image_id]
        rows.append({'ref': ref, 'image_id': image_id, 'container': cid, 'app': text((project or name).removeprefix('ix-').strip('/')),
                     'service': text(service or name.strip('/')), 'digests': digests or [], 'os': os_name, 'arch': arch,
                     'variant': variant or '', 'version': version or '', 'source': source or '', 'revision': revision or ''})
    return rows


def inventory():
    result = {'apps': [], 'images': [], 'pack': None}
    packages = ['apt-cacher-ng', 'tailscale', 'loki', 'grafana']
    for package in packages:
        try:
            current = command(['dpkg-query', '-W', '-f=${db:Status-Status} ${Version}', package])
            if not current.startswith('installed '):
                continue
            policy = command(['apt-cache', 'policy', package])
            candidate = re.search(r'Candidate:\s+(\S+)', policy).group(1)
            installed = current.split(' ', 1)[1]
            newer = subprocess.run(['dpkg', '--compare-versions', candidate, 'gt', installed],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            result['apps'].append({'app': package, 'current': text(installed), 'latest': text(candidate),
                                   'available': text(candidate) if newer else None, 'source': 'Configured APT repository'})
        except Exception:
            continue
    searx = Path('/usr/local/searxng/searxng-src')
    if (searx / '.git').exists():
        revision = command(['git', '-c', 'safe.directory=' + str(searx), '-C', str(searx), 'rev-parse', 'HEAD'])
        result['apps'].append({'app': 'searxng', 'current': revision, 'repository': 'searxng/searxng', 'branch': 'master'})
    if Path('/srv/tftp/netboot.xyz.kpxe').exists():
        files = ['/srv/tftp/netboot.xyz-unsigned.efi', '/srv/tftp/netboot.xyz.kpxe']
        result['apps'].append({'app': 'netboot_xyz', 'hashes': {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                                             for p in files if Path(p).exists()}})
    config = pack_config()
    if config:
        result['pack'] = {key: config.get(key, '') for key in ['PACK_NAME', 'PACK_SOURCE', 'MODPACK_SLUG', 'CURSEFORGE_PROJECT_ID', 'MC_VERSION', 'LOADER']}
        result['pack']['credential_available'] = bool(config.get('CURSEFORGE_API_KEY'))
        result['pack']['current_id'] = Path('/opt/minecraft/.current_version').read_text().strip()
    if shutil.which('docker'):
        result['images'] = docker_inventory()
    return result


def curseforge(packs):
    # The existing key stays inside its guest. Only selected version metadata returns.
    key = pack_config().get('CURSEFORGE_API_KEY')
    if not key:
        raise ValueError('CurseForge credential unavailable')
    rows = []
    for pack in packs:
        row = {'app': 'Minecraft: ' + text(pack['PACK_NAME']), 'vmid': pack['vmid'],
               'current': text(pack['current_id']), 'source': 'CurseForge', 'manual': pack['PACK_SOURCE'] == 'manual'}
        try:
            project, file_id = str(pack['CURSEFORGE_PROJECT_ID']), str(pack['current_id'])
            if not project.isdigit() or not file_id.isdigit():
                raise ValueError('Invalid CurseForge identity')
            base = 'https://api.curseforge.com/v1/mods/' + project + '/files'
            current = fetch(base + '/' + file_id, {'x-api-key': key})['data']
            query = urllib.parse.urlencode({'gameVersion': pack['MC_VERSION'], 'pageSize': 50})
            files = fetch(base + '?' + query, {'x-api-key': key})['data']
            candidates = [f for f in files if f.get('releaseType') == 1 and
                          bool(f.get('isServerPack')) == bool(current.get('isServerPack'))]
            latest = max(candidates, key=lambda f: f['fileDate'])
            row.update(current=text(current['displayName']), latest=text(latest['displayName']),
                       available=text(latest['displayName']) if latest['fileDate'] > current['fileDate'] else None)
        except Exception as error:
            row['unavailable'] = error_reason(error)
        rows.append(row)
    return rows


def modrinth(pack):
    current_id = pack['current_id']
    if not re.fullmatch(r'[A-Za-z0-9]{1,40}', current_id):
        raise ValueError('Invalid Modrinth version ID')
    current = public_json('https://api.modrinth.com/v2/version/' + current_id)
    project = current['project_id']
    if not re.fullmatch(r'[A-Za-z0-9]{1,40}', project):
        raise ValueError('Invalid Modrinth project ID')
    query = urllib.parse.urlencode({'game_versions': json.dumps([pack['MC_VERSION']]), 'loaders': json.dumps([pack['LOADER']])})
    candidates = public_json('https://api.modrinth.com/v2/project/' + project + '/version?' + query)
    latest = max((v for v in candidates if v['version_type'] == 'release'), key=lambda v: v['date_published'])
    return {'app': 'Minecraft: ' + text(pack['PACK_NAME']), 'vmid': pack['vmid'], 'source': 'Modrinth',
            'current': text(current['version_number']), 'latest': text(latest['version_number']),
            'available': text(latest['version_number']) if latest['date_published'] > current['date_published'] else None}


def native_upstream(row):
    if row['app'] == 'searxng':
        latest = public_json('https://api.github.com/repos/searxng/searxng/commits/master')['sha']
        comparison = public_json('https://api.github.com/repos/searxng/searxng/compare/' + row['current'] + '...' + latest)
        row.update(current=row['current'][:12], latest=latest[:12], source='GitHub master',
                   available=latest[:12] if comparison['ahead_by'] > 0 else None,
                   commits_behind=comparison['ahead_by'])
    elif row['app'] == 'netboot_xyz':
        releases = public_json('https://api.github.com/repos/netbootxyz/netboot.xyz/releases?per_page=20')
        stable = [r for r in releases if not r.get('draft') and not r.get('prerelease')]
        latest = max(stable, key=lambda r: r['published_at'])
        matches = [r for r in stable for a in r['assets'] if (a.get('digest') or '').removeprefix('sha256:') in row['hashes'].values()]
        row.update(latest=latest['tag_name'], source='GitHub release asset digest')
        if matches:
            installed = max(matches, key=lambda r: r['published_at'])
            row.update(current=installed['tag_name'], available=latest['tag_name'] if latest['published_at'] > installed['published_at'] else None)
        else:
            row.update(current='sha256:' + next(iter(row['hashes'].values()))[:12],
                       unavailable='Installed artifact digest absent from published release metadata')
        del row['hashes']
    return row


def image_target(image):
    ref = image['ref']
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/@:-]{0,250}', ref) or '://' in ref or
            ('@' in ref and not re.fullmatch(r'.+@sha256:[0-9a-f]{64}', ref))):
        raise ValueError('Invalid image reference')
    bare = ref.split('@', 1)[0]
    name, sep, tag = bare.rpartition(':')
    if not sep or '/' in tag:
        name, tag = bare, 'latest'
    if not image['digests']:
        return None
    # Preserve explicit release channels. Version pins compare against latest stable images.
    channel = tag if not re.match(r'^v?\d', tag) else 'latest'
    releases = {'ghcr.io/kineticman/fastchannels': 'kineticman/FastChannels',
                'ghcr.io/home-operations/sabnzbd': 'sabnzbd/sabnzbd', 'qmcgaw/gluetun': 'passteque/gluetun'}
    if name in releases and re.match(r'^v?\d', tag):
        channel = public_json('https://api.github.com/repos/' + releases[name] + '/releases/latest')['tag_name']
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}', channel):
            raise ValueError('Invalid release tag')
    return name + ':' + channel


def hub_update(image, target, row):
    name, tag = target.rsplit(':', 1)
    name = name.removeprefix('docker.io/').removeprefix('index.docker.io/')
    if '/' not in name:
        name = 'library/' + name
    namespace, repository = name.split('/', 1)
    if '.' in namespace or ':' in namespace:
        return None
    base = 'https://hub.docker.com/v2/namespaces/' + namespace + '/repositories/' + repository + '/tags'
    latest = public_json(base + '/' + tag)
    def platform(entry):
        return next(x['digest'] for x in entry['images'] if x['os'] == image['os'] and x['architecture'] == image['arch'] and
                    (not image.get('variant') or x.get('variant') == image['variant']))
    digest = platform(latest)
    installed = {d.rsplit('@', 1)[-1] for d in image['digests']}
    same = digest in installed or latest.get('digest') in installed
    tags = []
    label = tag
    if not re.match(r'^v?\d', tag) or not same:
        tags = public_json(base + '?page_size=100')['results']
    if not re.match(r'^v?\d', tag):
        aliases = [t['name'] for t in tags if re.fullmatch(r'v?\d+\.\d+[A-Za-z0-9._-]*', t['name']) and
                   any(x.get('digest') == digest for x in t['images'])]
        label = min(aliases, key=lambda value: (-len(re.match(r'v?([0-9.]+)', value)[1].split('.')), len(value))) if aliases else tag + ' ' + digest[:19]
    known_platform = same
    if not same:
        for old in tags:
            if old.get('digest') in installed:
                old_digest = platform(old)
                same, known_platform = old_digest == digest, True
                break
    row.update(latest=text(label), checked_image=target, source='Docker Hub tag/platform metadata',
               target_digest=digest,
               installed_digest=image['image_id'][:19], upstream_digest=digest[:19])
    if same:
        if re.match(r'^v?\d', row['current']):
            row['latest'] = row['current']
        else:
            row['current'] = row['latest']
        row['available'] = None
    else:
        row['available'] = row['latest']
        if not known_platform:
            row['available'] += ' (image index changed; platform needs review)'
            row['comparison_uncertain'] = True
        elif row['latest'].lstrip('v') == row['current'].lstrip('v'):
            row['available'] += ' (image manifest changed)'
        elif not re.match(r'^v?\d', row['latest']):
            row['available'] += ' (image manifest changed)'
    return row


def image_update(image, run=command):
    row = {'app': image['app'] + '/' + image['service'], 'kind': 'image', 'source': image['ref'],
           'current': image['ref'].split('@')[0].rsplit(':', 1)[-1] if ':' in image['ref'].split('@')[0] else image['image_id'][:19]}
    if re.fullmatch(r'v?\d+\.\d+\.\d+[A-Za-z0-9._-]*', image.get('version') or ''):
        row['current'] = text(image['version'])
    try:
        target = image_target(image)
        if target is None:
            repository = 'imputnet/cobalt' if image['app'] == 'cobalt' else None
            source = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', image.get('source') or '')
            repository = source[1] if source else repository
            if not repository:
                raise ValueError('Local image has no upstream source identity')
            revision = image.get('revision') or re.search(r':([0-9a-f]{7,40})(?:-|$)', image['ref'])[1]
            if not re.fullmatch(r'[0-9a-f]{7,40}', revision):
                raise ValueError('Invalid source revision')
            try:
                latest = public_json('https://api.github.com/repos/' + repository + '/releases/latest')
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                branch = public_json('https://api.github.com/repos/' + repository)['default_branch']
                commit = public_json('https://api.github.com/repos/' + repository + '/commits/' + urllib.parse.quote(branch, safe=''))['sha']
                latest = {'tag_name': commit, 'label': text(branch) + ' ' + commit[:12]}
            compare = public_json('https://api.github.com/repos/' + repository + '/compare/' + revision + '...' + urllib.parse.quote(latest['tag_name'], safe=''))
            label = latest.get('label', text(latest['tag_name']))
            row.update(current=revision[:12] + ' (local build)', latest=label,
                       available=label if compare['ahead_by'] > 0 else None,
                       source='GitHub ' + repository, manual=True)
            return row
        hub = hub_update(image, target, row)
        if hub is not None:
            return hub
        manifest = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect', target, '--format', '{{json .Manifest}}']))
        digest = manifest['digest']
        descriptor = manifest
        if 'manifests' in manifest:
            descriptor = next(m for m in manifest['manifests'] if m.get('platform', {}).get('os') == image['os'] and
                              m['platform'].get('architecture') == image['arch'] and
                              (not image.get('variant') or m['platform'].get('variant') == image['variant']))
            digest = descriptor['digest']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('Invalid manifest digest')
        installed = {d.rsplit('@', 1)[-1] for d in image['digests']}
        same = digest in installed or manifest['digest'] in installed
        platform_ref = target.rsplit(':', 1)[0] + '@' + digest
        if not same:
            platform = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect', platform_ref, '--raw']))
            same = platform['config']['digest'] == image['image_id']
        version = descriptor.get('annotations', {}).get('org.opencontainers.image.version')
        if not version:
            config = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect', platform_ref, '--format', '{{json .Image}}']))
            config = config.get(image['os'] + '/' + image['arch'], config)
            label = config.get('config', {}).get('Labels', {}).get('org.opencontainers.image.version', '')
            if re.fullmatch(r'v?\d+\.\d+\.\d+[A-Za-z0-9._-]*', label):
                version = label
            elif re.fullmatch(r'dev_\d+\.\d+\.\d+_[A-Za-z0-9_]+', label):
                version = label.split('_')[1] + ' (latest channel)'
        latest = text(version) if version else target.rsplit(':', 1)[-1] + ' ' + digest[:19]
        if same:
            if re.match(r'^v?\d', row['current']):
                latest = row['current']
            else:
                row['current'] = latest
        elif latest.lstrip('v') == row['current'].lstrip('v'):
            latest += ' (image rebuild)'
        row.update(latest=latest, available=latest if not same else None, checked_image=target,
                   target_digest=digest,
                   installed_digest=image['image_id'][:19], upstream_digest=digest[:19])
        if row['current'] in ('latest', 'stable', 'plexpass'):
            row['current'] += ' ' + image['image_id'][:19]
    except Exception as error:
        row['unavailable'] = error_reason(error)
    return row


def image_updates(images, run=command):
    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(lambda image: image_update(image, run), images))


def lxc_updates(guests, covered):
    source = Path(__file__).read_text()
    def guest_run(vmid, args):
        return command(['pct', 'exec', str(vmid), '--', *args], 120)
    def inspect(guest):
        try:
            return guest, json.loads(guest_run(guest['vmid'], ['python3', '-c', source, 'inventory']))
        except Exception as error:
            return guest, {'apps': [{'app': guest['name'], 'unavailable': error_reason(error)}], 'images': [], 'pack': None}
    rows, packs, credential_guests = [], [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        inventories = list(pool.map(inspect, [g for g in guests if g['status'] == 'running']))
    for guest, found in inventories:
        vmid = guest['vmid']
        for row in found['apps']:
            row['vmid'] = vmid
            try:
                native_upstream(row)
            except Exception as error:
                row['unavailable'] = error_reason(error)
            rows.append(row)
        for row in image_updates(found['images'], lambda args: guest_run(vmid, args)):
            row['vmid'] = vmid
            rows.append(row)
        if found['pack']:
            pack = found['pack']
            pack['vmid'] = vmid
            if pack.pop('credential_available'):
                credential_guests.append(vmid)
            if pack['PACK_SOURCE'] == 'manual':
                # Public project identities for the manually imported packs, not guest IDs.
                pack['CURSEFORGE_PROJECT_ID'] = {'All the Mods 10': '925200', 'Better MC [FORGE] - BMC4': '876781'}.get(pack['PACK_NAME'], '')
            if pack['CURSEFORGE_PROJECT_ID']:
                packs.append(pack)
            else:
                try:
                    rows.append(modrinth(pack))
                except Exception as error:
                    rows.append({'app': 'Minecraft: ' + text(pack['PACK_NAME']), 'vmid': vmid,
                                 'current': text(pack['current_id']), 'unavailable': error_reason(error)})
        if vmid not in covered and not found['apps'] and not found['images'] and not found['pack']:
            rows.append({'app': guest['name'] + ': OS packages', 'vmid': vmid, 'kind': 'os_only',
                         'current': 'No separate application detected', 'latest': 'Covered by package check'})
    if packs:
        try:
            rows.extend(json.loads(guest_run(credential_guests[0], ['python3', '-c', source, 'curseforge', json.dumps(packs)])))
        except Exception as error:
            rows.extend({'app': 'Minecraft: ' + text(p['PACK_NAME']), 'vmid': p['vmid'],
                         'current': text(p['current_id']), 'unavailable': error_reason(error)} for p in packs)
    return rows


if __name__ == '__main__':
    if sys.argv[1:] == ['inventory']:
        print(json.dumps(inventory()))
    elif sys.argv[1] == 'curseforge':
        print(json.dumps(curseforge(json.loads(sys.argv[2]))))
