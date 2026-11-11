"""
title: Homelab repairs
author: HomelabAnsible
version: 1.3.1
description: Review an exact app repair, approve once, and verify the result.
"""
import asyncio
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CONFIG = Path('/root/.config/homelab-repairs.json')
STATE = Path('/root/.open-webui/repair-plans')
FIELDS = {
    'host': ['allowedHosts'],
    'downloadclient': ['host', 'port', 'useSsl', 'urlBase'],
    'remotepathmapping': ['host', 'remotePath', 'localPath'],
    'plex': ['ip', 'port', 'useSsl'],
    'fixture': ['value'],
}
ACTIONS = {'arr': ['configure', 'restart'], 'sabnzbd': ['resume'],
           'seerr': ['configure', 'sync_libraries'], 'drill': ['configure']}
MAX_BYTES = 1024 * 1024


class RepairError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def without_scan_times(value):
    value = copy.deepcopy(value)
    for library in value.get('libraries', []):
        library.pop('lastScan', None)
    return value


def private_write(path, value):
    temporary = path.with_suffix('.tmp-' + uuid.uuid4().hex)
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def api(app, path, method='GET', body=None):
    url = app['url'] + path
    parsed = urllib.parse.urlsplit(app['url'])
    if (parsed.scheme not in ['http', 'https'] or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path
            or not ipaddress.ip_address(parsed.hostname).is_private):
        raise RepairError('The configured app endpoint is not a fixed private address.')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    if app['kind'] != 'sabnzbd':
        headers['X-Api-Key'] = app['key']
    payload = None if body is None else json.dumps(body).encode()
    try:
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(request, timeout=15) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RepairError('App response exceeds the size limit.')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise RepairError('App API returned HTTP ' + str(error.code) + '. No automatic retry.') from None
    except (OSError, ValueError, urllib.error.URLError):
        raise RepairError('App API unavailable or invalid response. No automatic retry.') from None


def projection(resource, value):
    if not isinstance(value, dict):
        raise RepairError('Unexpected app configuration format.')
    values = {x['name']: x.get('value') for x in value.get('fields', [])} if resource == 'downloadclient' else value
    result = {field: values[field] for field in FIELDS.get(resource, []) if field in values}
    if resource == 'plex' and 'libraries' in values:
        libraries = values['libraries']
        if not isinstance(libraries, list) or len(libraries) > 50 or not all(isinstance(x, dict) for x in libraries):
            raise RepairError('Unexpected library configuration format.')
        result['libraries'] = [{k: v for k, v in item.items() if k in ['id', 'name', 'type', 'enabled', 'lastScan']}
                               for item in libraries]
    return result


class Repairs:
    def __init__(self):
        if CONFIG.stat().st_mode & 0o077:
            raise RepairError('Repair credentials must have mode 0600.')
        self.config = json.loads(CONFIG.read_text())
        self.apps = self.config['apps'] | {'repair-drill': {'kind': 'drill', 'host': 'Open WebUI', 'resources': ['fixture']}}
        STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
        if STATE.stat().st_mode & 0o077:
            raise RepairError('Repair state must have mode 0700.')

    def authorize(self, user, metadata):
        if not user or user.get('role') != 'admin' or user.get('id') != self.config['owner_id']:
            raise RepairError('Only the configured owner may use repair tools.')
        if not metadata or not metadata.get('chat_id') or metadata.get('user_id') != user['id']:
            raise RepairError('An owner chat is required.')
        if metadata.get('automation_id') or metadata.get('internal'):
            raise RepairError('Repairs are unavailable to scheduled or internal requests.')

    def app(self, name):
        if name not in self.apps:
            raise RepairError('Unsupported app. Inspect repair options first.')
        return self.apps[name]

    def resource_path(self, app, resource, record_id=0):
        if resource not in app['resources'] or type(record_id) is not int or not 0 <= record_id <= 1000000:
            raise RepairError('Unsupported resource or record ID.')
        if app['kind'] == 'seerr':
            return '/api/v1/settings/plex'
        prefix = '/api/' + app.get('api_version', 'v3')
        return prefix + '/' + {'host': 'config/host', 'downloadclient': 'downloadclient',
                               'remotepathmapping': 'remotepathmapping'}[resource] + (('/' + str(record_id)) if record_id else '')

    def snapshot(self, name, action, resource, record_id):
        app = self.app(name)
        if app['kind'] == 'drill':
            path = STATE / 'drill-fixture.json'
            return json.loads(path.read_text()) if path.exists() else {'value': 'before'}
        if action == 'restart':
            return api(app, '/api/' + app.get('api_version', 'v3') + '/system/status')
        if action == 'resume':
            query = urllib.parse.urlencode({'mode': 'queue', 'output': 'json', 'limit': 0, 'apikey': app['key']})
            queue = api(app, '/api?' + query)['queue']
            return {'paused': queue['paused']}
        return api(app, self.resource_path(app, resource, record_id))

    def inspect(self, name, resource):
        if name == 'all':
            return {'apps': {key: {'host': app['host'], 'resources': app['resources'],
                                  'actions': ACTIONS[app['kind']]}
                             for key, app in self.apps.items()},
                    'limits': 'Only listed apps, fields, and actions. No shell, host, storage, credential, update, or deletion operations.'}
        app = self.app(name)
        result = {'app': name, 'host': app['host'], 'resources': app['resources'],
                  'allowed_hosts': app.get('allowed_hosts', []), 'destinations': app.get('destinations', {}),
                  'path_roots': app.get('path_roots', []),
                  'library_id_repairs': app.get('library_id_repairs', []),
                  'library_id_repairs_verified_at': app.get('library_id_repairs_verified_at'),
                  'library_catalog': app.get('library_catalog', []),
                  'actions': ACTIONS[app['kind']]}
        if resource:
            if resource not in app['resources']:
                raise RepairError('Unsupported resource.')
            if resource == 'queue':
                result['current'] = self.snapshot(name, 'resume', resource, 0)
            else:
                value = self.snapshot(name, 'configure', resource, 0)
                items = value if isinstance(value, list) else [value]
                result['records'] = [{'record_id': x.get('id', 0), 'values': projection(resource, x),
                                      **({'implementation': x['implementation']} if resource == 'downloadclient' else {})}
                                     for x in items[:30]]
                result['editable_fields'] = FIELDS[resource]
        return result

    def validate(self, app, resource, before, changes, restore=False):
        if not isinstance(changes, dict) or not changes or len(changes) > 4:
            raise RepairError('Supply one to four explicit field changes.')
        old = projection(resource, before)
        if set(changes) - old.keys() or set(changes) - set(FIELDS[resource]):
            raise RepairError('A requested field is absent or outside the repair allowlist.')
        for key, value in changes.items():
            if key == 'port':
                valid = type(value) is int and 1 <= value <= 65535
            elif key == 'useSsl':
                valid = type(value) is bool
            else:
                valid = isinstance(value, str) and len(value) <= 512 and all(32 <= ord(c) < 127 for c in value)
            if not valid:
                raise RepairError('Invalid field value or type.')
        updated = old | changes
        if resource == 'fixture' and updated['value'] not in ['before', 'after']:
            raise RepairError('The drill accepts only before or after.')
        if resource == 'host':
            hosts = [x.strip() for x in updated['allowedHosts'].split(',') if x.strip()]
            required = app.get('required_hosts', [])
            if (not hosts or set(hosts) - set(app.get('allowed_hosts', [])) or set(required) - set(hosts)) and not restore:
                raise RepairError('Allowed hosts must include the configured access names and contain no wildcards or unknown names.')
        if resource in ['downloadclient', 'plex']:
            kind = before.get('implementation', 'plex')
            destination = {k: updated.get(k) for k in FIELDS[resource]}
            if resource == 'downloadclient':
                destination['urlBase'] = destination['urlBase'] or ''
            if destination not in app.get('destinations', {}).get(kind, []):
                raise RepairError('Connection changes must match an explicitly configured destination, including port and TLS.')
        if resource == 'remotepathmapping':
            if updated['host'] not in app.get('allowed_hosts', []):
                raise RepairError('Unknown mapping host.')
            for key in ['remotePath', 'localPath']:
                value = updated[key]
                if ('..' in value.split('/') or not any(value == root or value.startswith(root.rstrip('/') + '/')
                                                       for root in app.get('path_roots', []))):
                    raise RepairError('Mapping paths must stay inside the configured media roots.')
        return {k: {'before': old[k], 'after': v} for k, v in changes.items() if old[k] != v}

    def catalog(self, libraries):
        if not isinstance(libraries, list) or len(libraries) > 50:
            raise RepairError('Unexpected library catalog.')
        try:
            result = [{k: item[k] for k in ['id', 'name', 'type', 'enabled']} for item in libraries]
            if any(not isinstance(x['id'], str) or not re.fullmatch(r'[1-9][0-9]{0,8}', x['id'])
                   or not isinstance(x['name'], str) or not 1 <= len(x['name']) <= 512
                   or x['type'] not in ['movie', 'show']
                   or type(x['enabled']) is not bool for x in result) or len({x['id'] for x in result}) != len(result):
                raise ValueError()
            return sorted(result, key=lambda x: x['id'])
        except (KeyError, TypeError, ValueError):
            raise RepairError('Unexpected library catalog fields.') from None

    def sync_target(self, app, before):
        if not 0 <= time.time() - app.get('library_id_repairs_verified_at', 0) <= 3600:
            raise RepairError('Plex catalog evidence is older than one hour. Recheck Plex before a new proposal.')
        target = copy.deepcopy(projection('plex', before)['libraries'])
        matches = 0
        for pair in app.get('library_id_repairs', []):
            for library in target:
                if (library['id'], library['name'], library['type']) == (pair['from_id'], pair['name'], pair['type']):
                    library['id'] = pair['to_id']
                    library.pop('lastScan', None)
                    matches += 1
        if matches != 1:
            raise RepairError('Exactly one verified replacement must match the current Seerr catalog.')
        actual = [{k: x[k] for k in ['id', 'name', 'type']} for x in self.catalog(target)]
        if actual != sorted(app.get('library_catalog', []), key=lambda x: x['id']):
            raise RepairError('The expected catalog differs from the verified Plex evidence.')
        return target

    def prepare(self, name, action, resource, record_id, changes, owner, chat, restore=False, message=None):
        if not isinstance(message, str) or not message:
            raise RepairError('Prepare repairs in a saved chat message.')
        app = self.app(name)
        if action not in ['configure', 'restart', 'resume', 'sync_libraries']:
            raise RepairError('Unsupported repair action.')
        if action == 'restart' and app['kind'] != 'arr' or action == 'resume' and app['kind'] != 'sabnzbd':
            raise RepairError('This recovery action is not supported for the app.')
        if action == 'sync_libraries' and app['kind'] != 'seerr':
            raise RepairError('Library sync is available only for Seerr.')
        if action == 'configure' and (resource not in app['resources'] or resource not in FIELDS):
            raise RepairError('Unsupported configuration resource.')
        if action != 'configure' and changes:
            raise RepairError('Recovery actions accept no field changes.')
        if action != 'configure':
            resource, record_id = {'restart': 'system', 'resume': 'queue', 'sync_libraries': 'plex'}[action], 0
        before = self.snapshot(name, action, resource, record_id)
        if not isinstance(before, dict):
            raise RepairError('Select a single record ID before proposing a change.')
        if action == 'configure' and resource == 'host':
            record_id = before['id']
        diff = self.validate(app, resource, before, changes, restore) if action == 'configure' else {}
        if action == 'sync_libraries':
            target = self.sync_target(app, before)
            diff = {'libraries': {'before': projection('plex', before)['libraries'], 'after': target}}
        if action == 'configure' and not diff:
            raise RepairError('Those values already match. No repair is needed.')
        if action == 'resume' and before.get('paused') is not True:
            raise RepairError('This queue is not paused. No resume is needed.')
        ident = uuid.uuid4().hex
        plan = {'id': ident, 'app': name, 'host': app['host'], 'action': action, 'resource': resource,
                'record_id': record_id, 'diff': diff, 'before': before, 'policy': digest(self.config),
                'owner': owner, 'chat': chat, 'message': message, 'created': time.time(), 'expires': time.time() + 600,
                'status': 'proposed', 'restore': restore, 'backup': str(STATE / (ident + '.backup.json')),
                'risk': {'configure': 'Only these settings change. App jobs can behave differently immediately. No service restart is included.',
                         'restart': 'This app will briefly disconnect. Active jobs can be interrupted. No configuration change is included.',
                         'sync_libraries': 'Refresh Seerr libraries from Plex, then restore the approved enabled selection. Replaced libraries lose their old scan marker. A partial failure can leave the replaced library disabled. Unexpected catalog changes stop follow-up writes. No automatic rollback or service restart.',
                         'resume': 'Queued downloads will resume and consume network bandwidth and storage. No configuration change is included.'}[action]}
        if app['kind'] == 'seerr' and action == 'configure':
            plan['risk'] += ' Seerr tests Plex and can update its detected server name and ID. A failed API response can leave in-memory settings changed.'
        if action == 'sync_libraries':
            plan['steps'] = ['Refresh the complete library list from the current Plex server.',
                             'Restore enabled=true only for the approved replacement library if previously enabled.']
        if app['kind'] == 'drill':
            plan['risk'] = 'DRILL: changes only a disposable repair fixture inside Open WebUI. No homelab service is affected.'
        private_write(STATE / (ident + '.json'), plan)
        return self.public(plan)

    def load(self, ident, owner, chat):
        if not re.fullmatch(r'[a-f0-9]{32}', ident):
            raise RepairError('Invalid repair ID.')
        try:
            plan = json.loads((STATE / (ident + '.json')).read_text())
        except FileNotFoundError:
            raise RepairError('Unknown repair ID.') from None
        if plan['owner'] != owner or plan['chat'] != chat:
            raise RepairError('This proposal belongs to another owner or chat.')
        return plan

    def public(self, plan):
        return {k: plan[k] for k in ['id', 'app', 'host', 'action', 'resource', 'record_id', 'diff', 'status', 'expires', 'backup', 'risk', 'result', 'steps', 'steps_completed'] if k in plan}

    def save(self, plan, status, result=None):
        plan['status'] = status
        if result is not None:
            plan['result'] = result
        private_write(STATE / (plan['id'] + '.json'), plan)

    def apply(self, plan):
        app = self.app(plan['app'])
        current = self.snapshot(plan['app'], plan['action'], plan['resource'], plan['record_id'])
        library_repair = plan['action'] == 'sync_libraries'
        observed = without_scan_times(current) if library_repair else current
        expected = without_scan_times(plan['before']) if library_repair else plan['before']
        if plan['policy'] != digest(json.loads(CONFIG.read_text())) or digest(observed) != digest(expected):
            raise RepairError('App state or repair policy changed. Prepare a fresh proposal.')
        changes = {k: v['after'] for k, v in plan['diff'].items()}
        if library_repair:
            changes['libraries'] = self.sync_target(app, current)
            if digest(without_scan_times(changes)) != digest(without_scan_times({'libraries': plan['diff']['libraries']['after']})):
                raise RepairError('The expected catalog changed. Prepare a new proposal.')
        if plan['action'] == 'configure':
            self.validate(app, plan['resource'], current, changes, plan.get('restore', False))
        private_write(Path(plan['backup']), {'app': plan['app'], 'resource': plan['resource'],
                                            'record_id': plan['record_id'], 'saved_at': time.time(), 'before': current})
        self.save(plan, 'attempting')
        if app['kind'] == 'drill':
            private_write(STATE / 'drill-fixture.json', current | {k: d['after'] for k, d in plan['diff'].items()})
        elif library_repair:
            synced = api(app, '/api/v1/settings/plex/library/sync', 'POST')
            plan['steps_completed'] = ['Library sync request completed.']
            self.save(plan, 'attempting')
            old_ids = {x['id'] for x in current['libraries']}
            expected = copy.deepcopy(changes['libraries'])
            for item in expected:
                if item['id'] not in old_ids:
                    item['enabled'] = False
            if self.catalog(synced) != self.catalog(expected):
                raise RepairError('Sync returned an unexpected catalog. No enable request was sent. Inspect Seerr before another attempt.')
            for item in changes['libraries']:
                if item['id'] not in old_ids and item['enabled']:
                    api(app, '/api/v1/settings/plex/library/' + item['id'], 'PUT', {'enabled': True})
                    plan['steps_completed'].append('Enabled replacement library ' + item['id'] + '.')
                    self.save(plan, 'attempting')
        elif plan['action'] == 'configure':
            body = copy.deepcopy(current)
            for key, value in changes.items():
                if plan['resource'] == 'downloadclient':
                    next(x for x in body['fields'] if x['name'] == key)['value'] = value
                else:
                    body[key] = value
            path = self.resource_path(app, plan['resource'], plan['record_id'])
            if app['kind'] == 'seerr':
                # Seerr requires ip and port; name, machineId, and libraries are read-only.
                body = {k: body[k] for k in FIELDS['plex'] if k in body}
            api(app, path, 'POST' if app['kind'] == 'seerr' else 'PUT', body)
        elif plan['action'] == 'restart':
            api(app, '/api/' + app.get('api_version', 'v3') + '/system/restart', 'POST', {})
        else:
            query = urllib.parse.urlencode({'mode': 'resume', 'output': 'json', 'apikey': app['key']})
            result = api(app, '/api?' + query)
            if result.get('status') is not True:
                raise RepairError('The queue did not acknowledge resume. Inspect before another proposal.')

    def verify(self, plan):
        # Read retries do not authorize a second mutation.
        for attempt in range(6):
            try:
                value = self.snapshot(plan['app'], plan['action'], plan['resource'], plan['record_id'])
                if plan['action'] == 'configure':
                    actual = projection(plan['resource'], value)
                    expected = {k: d['after'] for k, d in plan['diff'].items()}
                    ok = all(actual.get(k) == v for k, v in expected.items())
                    detail = 'Exact settings verified. Use fresh app health and logs to determine whether the original issue is resolved.'
                elif plan['action'] == 'sync_libraries':
                    ok = (self.catalog(value['libraries']) == self.catalog(plan['diff']['libraries']['after'])
                          and all(value.get(k) == plan['before'].get(k) for k in FIELDS['plex']))
                    detail = 'Library IDs and enabled selection verified. A successful subsequent scan remains to be checked.'
                elif plan['action'] == 'resume':
                    ok, detail = value.get('paused') is False, 'The queue is no longer paused. Download success remains unverified.'
                else:
                    ok = bool(value.get('startTime')) and value.get('startTime') != plan['before'].get('startTime')
                    detail = 'A new app start time is verified. Use fresh health and logs to check the original issue.'
                if ok:
                    return {'verified': True, 'detail': detail}
            except RepairError:
                pass
            if attempt < 5:
                time.sleep(3)
        return {'verified': False, 'detail': 'The attempt was sent, but verification did not pass. Do not repeat automatically. Inspect current state.'}


async def status(emitter, text, done=False):
    if emitter:
        try:
            await emitter({'type': 'status', 'data': {'description': text, 'done': done, 'hidden': False}})
        except Exception:
            pass  # Delivery failure must not turn a completed write into a retry.


class Tools:
    async def inspect_repair_options(self, app: str = 'all', resource: str = '', __user__: dict = None, __metadata__: dict = None) -> dict:
        """Read repair capabilities or current editable settings. app=all lists targets. Resources: host, downloadclient, remotepathmapping, plex, queue, fixture. Never changes an app."""
        engine = Repairs()
        engine.authorize(__user__, __metadata__)
        return await asyncio.to_thread(engine.inspect, app, resource)

    async def prepare_repair(self, app: str, changes: dict, action: str = 'configure', resource: str = 'host', record_id: int = 0,
                             __user__: dict = None, __metadata__: dict = None) -> dict:
        """Prepare an exact proposal without changing an app. Inspect options first. configure uses a flat changes object. restart/resume/sync_libraries use changes={}. Seerr libraries are read-only fields: use sync_libraries, which refreshes the complete catalog then restores the approved replacement enabled flag. Its old scan marker resets; no automatic rollback. For a safe drill use app=repair-drill, resource=fixture, and toggle value between before and after. Tell the owner to click Review repair beneath this message, then Approve repair or Cancel repair. Only the buttons can authorize an attempt; there is no approval tool or popup."""
        engine = Repairs()
        engine.authorize(__user__, __metadata__)
        return await asyncio.to_thread(engine.prepare, app, action, resource, record_id, changes,
                                       __user__['id'], __metadata__['chat_id'], message=__metadata__.get('message_id'))

    async def prepare_rollback(self, repair_id: str, __user__: dict = None, __metadata__: dict = None) -> dict:
        """Prepare a separately approved reversal of one configuration repair in this chat. Does not execute it. Recovery actions have no configuration rollback."""
        engine = Repairs()
        engine.authorize(__user__, __metadata__)
        previous = engine.load(repair_id, __user__['id'], __metadata__['chat_id'])
        if previous['action'] != 'configure' or previous['status'] not in ['verified', 'unverified', 'failed_or_uncertain']:
            raise RepairError('No attempted configuration repair is available to reverse.')
        return await asyncio.to_thread(engine.prepare, previous['app'], 'configure', previous['resource'], previous['record_id'],
                                       {k: v['before'] for k, v in previous['diff'].items()}, __user__['id'], __metadata__['chat_id'], True, message=__metadata__.get('message_id'))

    async def repair_status(self, repair_id: str, __user__: dict = None, __metadata__: dict = None) -> dict:
        """Read the saved proposal, backup receipt, and result. An attempting status after interruption means outcome unknown. Never repeat it automatically."""
        engine = Repairs()
        engine.authorize(__user__, __metadata__)
        return engine.public(engine.load(repair_id, __user__['id'], __metadata__['chat_id']))



def review_text(plan):
    expires = datetime.fromtimestamp(plan['expires'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    text = (f"### Repair review: {plan['app']}\n\n"
            f"**{plan['host']} · {plan['action']} · {plan['status'].replace('_', ' ')}**\n\n"
            f"Proposal: `{plan['id']}` · Expires: {expires}\n\n"
            + '```json\n' + json.dumps(plan['diff'], indent=2) + '\n```\n\n'
            + '\n'.join(f"{i}. {step}" for i, step in enumerate(plan.get('steps', []), 1))
            + '\n\n' + plan['risk'] + '\n\nBackup before the attempt: `' + plan['backup'] + '`.'
            + '\n\nFor restart/resume, the backup is a precheck receipt, not an application-data backup.')
    if plan['status'] == 'proposed':
        text += '\n\nSelect **Approve repair** below to authorize this one attempt, or **Cancel repair**. No popup. No automatic retry.'
    if plan.get('result'):
        text += '\n\n**Result:** ' + plan['result'].get('detail', '')
    if plan.get('steps_completed'):
        text += '\n\nCompleted: ' + ' '.join(plan['steps_completed'])
    return text


async def saved_message(chat, owner, message):
    from open_webui.models.chats import Chats
    if not await Chats.get_chat_by_id_and_user_id(chat, owner):
        raise RepairError('The repair chat must belong to the configured owner.')
    value = await Chats.get_message_by_id_and_message_id(chat, message)
    if not value or value.get('role') != 'assistant' or value.get('model') != 'ask-the-lab' or value.get('done') is not True:
        raise RepairError('Select a completed Ask the lab proposal message.')
    return value


async def show_message(chat, message, content, emitter):
    from open_webui.models.chats import Chats
    update = {'id': message, 'content': content, 'output': [], 'done': True, 'error': None}
    if not await Chats.upsert_message_to_chat_by_id_and_message_id(chat, message, update):
        raise RepairError('Could not save the repair message. Check repair_status before another attempt.')
    if emitter:
        try:
            await emitter({'type': 'chat:completion', 'data': update})
        except Exception:
            pass  # The HTTP response and saved chat remain available without WebSockets.
    return {'messages': [update]}


class Action:
    # Tiny inline SVGs keep the three buttons distinct without an external image host.
    actions = [
        {'id': ident, 'name': name, 'icon_url': 'data:image/svg+xml,' + urllib.parse.quote(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="' + color +
            '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + shape + '</svg>')}
        for ident, name, color, shape in [
            ('review', 'Review repair', '#6b9fff', '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>'),
            ('approve', 'Approve repair', '#22c55e', '<path d="m4 12 5 5 11-11"/>'),
            ('cancel', 'Cancel repair', '#ef4444', '<path d="m6 6 12 12M6 18 18 6"/>')]]

    async def action(self, body: dict, __id__=None, __user__=None, __model__=None, __request__=None, __event_emitter__=None):
        engine = Repairs()
        engine.authorize(__user__, {'chat_id': body.get('chat_id'), 'user_id': (__user__ or {}).get('id')})
        if (__id__ not in ['review', 'approve', 'cancel'] or not __request__
                or __request__.method != 'POST'
                or __request__.url.path != '/api/chat/actions/homelab_repair_controls.' + __id__
                or body.get('model') != 'ask-the-lab' or (__model__ or {}).get('id') != 'ask-the-lab'):
            raise RepairError('Use the repair buttons in Ask the lab. Models and chat text cannot approve.')
        chat, message = body['chat_id'], body.get('id')
        value = await saved_message(chat, __user__['id'], message)
        with open(STATE / 'execution.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RepairError('A repair is already running. Check its saved result before another attempt.') from None
            plans = []
            for path in STATE.glob('*.json'):
                if re.fullmatch(r'[a-f0-9]{32}\.json', path.name):
                    candidate = json.loads(path.read_text())
                    if (candidate.get('owner'), candidate.get('chat'), candidate.get('message')) == (__user__['id'], chat, message):
                        plans.append(candidate)
            if len(plans) != 1:
                raise RepairError('This message needs exactly one new repair proposal. Ask for a fresh proposal in this chat.')
            plan = plans[0]
            if plan['status'] != 'proposed':
                return await show_message(chat, message, review_text(plan), __event_emitter__)
            if time.time() >= plan['expires']:
                engine.save(plan, 'expired', {'detail': 'The proposal expired. Ask for a fresh proposal.'})
                return await show_message(chat, message, review_text(plan), __event_emitter__)
            if __id__ == 'review':
                content = review_text(plan)
                response = await show_message(chat, message, content, __event_emitter__)
                plan['review_hash'] = digest(content)
                engine.save(plan, 'proposed')
                return response
            if __id__ == 'cancel':
                engine.save(plan, 'canceled', {'detail': 'Canceled by the owner. No repair ran.'})
                return await show_message(chat, message, review_text(plan), __event_emitter__)
            content = review_text(plan)
            visible = [m for m in body.get('messages', [])
                       if isinstance(m, dict) and m.get('id') == message and m.get('role') == 'assistant']
            if (plan.get('review_hash') != digest(content) or value.get('content') != content
                    or len(visible) != 1 or visible[0].get('content') != content):
                raise RepairError('Click Review repair first, read the saved plan, then click Approve repair on that message.')
            plan['approved_at'] = time.time()
            plan['approval_method'] = 'owner_action_button'
            engine.save(plan, 'approved')
            try:
                async def attempt():
                    await show_message(chat, message, review_text(plan) + '\n\n**Working: checking state and saving the backup…**', __event_emitter__)
                    await status(__event_emitter__, 'Working: checking current state and saving the backup…')
                    await asyncio.to_thread(engine.apply, plan)
                    await status(__event_emitter__, 'Working: attempt sent. Verifying the result…')
                    result = await asyncio.to_thread(engine.verify, plan)
                    engine.save(plan, 'verified' if result['verified'] else 'unverified', result)
                worker = asyncio.create_task(attempt())
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    await worker
                    raise
            except asyncio.CancelledError:
                if plan['status'] not in ['verified', 'unverified']:
                    engine.save(plan, 'failed_or_uncertain' if plan['status'] == 'attempting' else 'blocked',
                                {'detail': 'Interrupted. Inspect current state. Never repeat automatically.'})
                raise
            except Exception as error:
                engine.save(plan, 'failed_or_uncertain' if plan['status'] == 'attempting' else 'blocked',
                            {'detail': str(error) if isinstance(error, RepairError) else 'Operation failed. Inspect current app state. No automatic retry.'})
            finally:
                await status(__event_emitter__, 'Repair: ' + plan['status'].replace('_', ' '), done=True)
            return await show_message(chat, message, review_text(plan), __event_emitter__)
