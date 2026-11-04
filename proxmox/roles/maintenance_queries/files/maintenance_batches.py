#!/usr/bin/python3
"""A single owner approval for immutable, sequential multi-host maintenance."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import urllib.error
import urllib.parse

TITLE = '**Maintenance batch**'
PREPARE_UNIT = 'homelab-batch-prepare'
EXECUTE_UNIT = 'homelab-batch-execute'
TERMINAL = ('completed', 'failed', 'stopped')
SCOPES = {'all': 'Applications and OS packages', 'apps': 'Applications only', 'os': 'OS packages only'}


class AwaitingDisplay(Exception):
    """A coordinator message edit is not yet visible consistently."""


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


backend = load('batch_app_backend', Path(__file__).with_name('app_update_backends.py'))
adapters = load('batch_backends', Path(__file__).with_name('batch_backends.py'))


def read(config):
    path = Path(config['state_dir']) / 'maintenance-batch.json'
    return json.loads(path.read_text()) if path.exists() else {}


def active(config):
    return read(config).get('status') == 'active'


@contextlib.contextmanager
def locked(config):
    with (Path(config['state_dir']) / 'maintenance-batch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def save(q, config, item):
    q.save(Path(config['state_dir']) / 'maintenance-batch.json', item)
    fd = os.open(config['state_dir'], os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def implementation(config):
    paths = [Path(config['_config_path'])]
    paths += [Path(__file__).with_name(name) for name in ('maintenance_batches.py', 'batch_backends.py',
              'approved_apt.py', 'app_update_backends.py', 'app_update_requests.py', 'app_versions.py')]
    paths += [path for path in (Path(__file__).with_name('homelab-status'), Path(__file__).with_name('homelab-status.py')) if path.exists()]
    if config['platform'] == 'pve':
        paths += [adapters.OS_CONFIG]
        paths += sorted(path for path in backend.APP_ROOT.rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    return backend.digest({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})


def start(config, prepare=False):
    unit = PREPARE_UNIT if prepare else EXECUTE_UNIT
    subprocess.run(['systemd-run', '--quiet', '--collect', '--unit=' + unit, '--property=Type=exec',
                    '--property=UMask=0077', '--property=TimeoutStartSec=infinity', '/usr/bin/python3',
                    str(Path(__file__).resolve()), '--prepare' if prepare else '--execute', '--config', config['_config_path']],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def unit_active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit + '.service'], timeout=15).returncode == 0


def request(q, config, message, host, scope='all'):
    if scope not in SCOPES:
        raise ValueError('Unsupported maintenance scope')
    nodes = config.get('query_nodes', [config['node']]) if host == '*' else [host]
    if config['node'] not in nodes:
        return
    with locked(config):
        previous = read(config)
        if previous.get('id') == message['id']:
            return
        if previous.get('status') == 'active' or unit_active(PREPARE_UNIT) or unit_active(EXECUTE_UNIT):
            if config['node'] == nodes[0]:
                q.discord(config, 'POST', payload={'content': 'A maintenance batch is already active. Finish or cancel it first.',
                          'allowed_mentions': {'parse': []}, 'nonce': 'busy-' + message['id'], 'enforce_nonce': True})
            return
        if previous:
            q.save(Path(config['state_dir']) / ('batch-' + previous['id'] + '.json'), previous)
        item = {'id': message['id'], 'owner': config['owner_user_id'], 'channel': config['channel_id'], 'nodes': nodes,
                'scope': scope, 'created': time.time(), 'status': 'active',
                'local': {'phase': 'waiting', 'stage': 'Waiting for the details thread.'}}
        save(q, config, item)
        poll_locked(q, config, item)


def parent(q, config, item):
    if not item.get('parent'):
        messages = q.discord(config, suffix='?limit=100&after=' + item['id'])
        found = [m for m in messages if m.get('author', {}).get('id') == config['bot_user_id'] and not m.get('webhook_id') and
                 m.get('message_reference', {}).get('message_id') == item['id'] and m.get('content', '').startswith(TITLE)]
        if len(found) > 1:
            raise ValueError('Duplicate batch summaries')
        if not found:
            if config['node'] != item['nodes'][0]:
                return False
            if len(messages) == 100:
                raise ValueError('Cannot safely locate the batch summary')
            receipt = q.discord(config, 'POST', payload={'content': TITLE + '\nScope: ' + SCOPES[item.get('scope', 'all')] +
                                '\n⏳ Working… Preparing exact plans. No updates are authorized.',
                                'allowed_mentions': {'parse': []}, 'message_reference': {'message_id': item['id'], 'fail_if_not_exists': False},
                                'nonce': 'batch-' + item['id'], 'enforce_nonce': True})
        else:
            receipt = found[0]
        if receipt.get('channel_id') != config['channel_id'] or not q.ID.fullmatch(receipt.get('id', '')):
            raise ValueError('Unconfirmed batch summary')
        item['parent'] = receipt['id']
        save(q, config, item)
    receipt = q.discord(config, suffix='/' + item['parent'])
    thread = receipt.get('thread')
    if not thread:
        if config['node'] != item['nodes'][0]:
            return False
        try:
            thread = q.discord(config, 'POST', '/' + item['parent'] + '/threads',
                               {'name': 'Maintenance plans and progress', 'auto_archive_duration': 1440})
        except urllib.error.HTTPError as error:
            if error.code == 400 and json.loads(error.read(8192)).get('code') == 160004:
                return False
            raise
    if thread.get('id') != item['parent'] or thread.get('parent_id') != config['channel_id'] or thread.get('type') != 11:
        raise ValueError('Unexpected batch thread')
    return True


def manifest(config, plan):
    lines = [config['node'] + ' — ' + SCOPES[plan.get('scope', 'all')], 'Only the listed actions are approved. No reboots or package removals.', '']
    for i, action in enumerate(plan['actions'], 1):
        lines += [str(i) + '. ' + action['label'], action['effect']]
        for row in action.get('apt', {}).get('packages', action.get('package_changes', [])):
            lines.append('  ' + row['package'] + ': ' + str(row['from'] or '(new dependency)') + ' -> ' + row['to'])
        lines.append('')
    lines += ['Excluded/current items and notices:', *plan['notes']]
    return '\n'.join(lines)


def metadata(item, config):
    local = item['local']
    return {'kind': 'host', 'batch': item['id'], 'node': config['node'], 'phase': local['phase'], 'scope': item.get('scope', 'all'),
            'seal': local.get('seal'), 'count': len(local.get('plan', {}).get('actions', [])),
            'notices': len(local.get('plan', {}).get('notes', [])), 'done': len(local.get('results', [])),
            'stage': local.get('stage', '')[:180], 'heartbeat': int(time.time()) // 60}


def publish_local(q, config, item):
    local = item['local']
    meta = metadata(item, config)
    text = local.get('manifest')
    attach = text is not None and not local.get('attachment')
    needs_result = local['phase'] in TERMINAL and local.get('results') is not None and not local.get('result_attachment')
    if meta == local.get('published') and not attach and not needs_result:
        return
    payload = {'content': '', 'embeds': [{'title': config['node'] + ' · Maintenance batch',
               'description': local['phase'].title() + '\n' + local.get('stage', '')[:300],
               'footer': {'text': json.dumps(meta, separators=(',', ':'))}}], 'allowed_mentions': {'parse': []}}
    filename = 'maintenance-plan-' + config['node'] + '.txt'
    kwargs = {}
    if attach:
        payload['attachments'] = [{'id': 0, 'filename': filename}]
        kwargs['attachment'] = (filename, text)
    if needs_result:
        result_name = 'maintenance-result-' + config['node'] + '.txt'
        result_text = '\n\n'.join(row['label'] + '\n' + row['result'] for row in local['results'])
        result_text += '\n\n' + local.get('stage', '') + '\nRemaining actions were not automatically retried.'
        payload['attachments'] = ([{'id': local['attachment']}] if local.get('attachment') else []) + [{'id': 0, 'filename': result_name}]
        kwargs['attachment'] = (result_name, result_text)
    if not local.get('message'):
        payload.update(nonce=hashlib.sha256((item['id'] + config['node'] + 'batch-host').encode()).hexdigest()[:24], enforce_nonce=True)
    target = {**config, 'channel_id': item['parent']}
    receipt = q.discord(target, 'PATCH' if local.get('message') else 'POST', '/' + local['message'] if local.get('message') else '', payload, **kwargs)
    if receipt.get('channel_id') != item['parent'] or not q.ID.fullmatch(receipt.get('id', '')):
        raise ValueError('Unconfirmed host batch result')
    local['message'] = receipt['id']
    if attach:
        attachments = receipt.get('attachments', [])
        if len(attachments) != 1 or attachments[0].get('filename') != filename:
            raise ValueError('Unconfirmed plan attachment')
        local['attachment'] = attachments[0]['id']
    if needs_result:
        if not any(a.get('filename') == result_name for a in receipt.get('attachments', [])):
            raise ValueError('Unconfirmed result attachment')
        local['result_attachment'] = True
    local['published'] = meta
    save(q, config, item)


def records(q, config, item):
    messages = q.discord({**config, 'channel_id': item['parent']}, suffix='?limit=100')
    hosts, control = {}, None
    for message in messages:
        if message.get('author', {}).get('id') != config['bot_user_id'] or message.get('webhook_id'):
            continue
        for embed in message.get('embeds', []):
            try:
                value = json.loads(embed.get('footer', {}).get('text', ''))
            except (ValueError, TypeError):
                continue
            if not isinstance(value, dict) or value.get('batch') != item['id']:
                continue
            if value.get('kind') == 'host' and value.get('node') in item['nodes']:
                if value.get('phase') == 'prepared' and not any(a.get('filename') == 'maintenance-plan-' + value['node'] + '.txt'
                                                               for a in message.get('attachments', [])):
                    continue
                if value['node'] in hosts:
                    raise ValueError('Duplicate batch host records')
                value['message'] = message['id']
                hosts[value['node']] = value
            elif value.get('kind') == 'control':
                if control is not None:
                    raise ValueError('Duplicate batch control records')
                control = value
    return hosts, control


def reacted(q, config, item, emoji):
    suffix = '/' + item['parent'] + '/reactions/' + urllib.parse.quote(emoji, safe='')
    users = q.discord(config, suffix=suffix + '?type=0&after=' + str(int(config['owner_user_id']) - 1) + '&limit=1')
    return any(user.get('id') == config['owner_user_id'] and not user.get('bot') for user in users)


def summary(item, control, hosts):
    phase = control['phase']
    label = {'collecting': '⏳ Working… Preparing exact plans.', 'proposed': '⏸ Review the attached plans, then approve once.',
             'running': '⏳ Working… ' + str(control.get('active') or 'Finishing'),
             'completed': '✅ Batch finished.', 'failed': '⛔ Batch stopped after a failure.',
             'stopped': 'Canceled or expired. No further actions will start.'}[phase]
    lines = [TITLE, 'Scope: ' + SCOPES[item.get('scope', 'all')], label]
    for node in item['nodes']:
        row = hosts.get(node)
        if row:
            status = row['phase']
            if phase in ('stopped', 'failed') and status in ('waiting', 'queued', 'prepared'):
                status = 'last reported: ' + status if control.get('approved') else 'not started'
            lines.append('**' + node + '**: ' + str(row['done']) + '/' + str(row['count']) + ' actions · ' + status +
                         ' · ' + str(row['notices']) + ' notices/exclusions')
        else:
            lines.append('**' + node + '**: waiting for this host')
    if phase == 'proposed':
        lines += ['Exact versions and exclusions are in each host’s attached plan in the thread.',
                  'Services may restart. Fresh guest backups run first. Host copies are configuration-only; TrueNAS backups can be up to 30 hours old.',
                  'No reboots. Stop on the first failure. ✅ Approve this batch · ❌ Cancel.',
                  f'Approval expires <t:{int(control["expires"])}:R>. Execution window: six hours.']
    elif phase == 'running':
        lines.append('❌ stops pending actions after the current transaction. No automatic retries or reboots.')
    if control.get('reason'):
        lines.append(control['reason'][:240])
    lines += ['Full plans and results are in the thread below.', 'Model: none · API cost: $0.000000']
    result = '\n'.join(lines)
    if len(result) > 1900:
        raise ValueError('Batch summary exceeds limit')
    return result


def publish_control(q, config, item, control, hosts):
    content = summary(item, control, hosts)
    if item.get('display') != content:
        receipt = q.discord(config, 'PATCH', '/' + item['parent'], {'content': content, 'embeds': [], 'allowed_mentions': {'parse': []}})
        if receipt.get('content') != content:
            raise ValueError('Unconfirmed batch summary')
        item['display'] = content
    control['display'] = hashlib.sha256(content.encode()).hexdigest()
    encoded = json.dumps(control, separators=(',', ':'))
    if len(encoded) > 2048:
        raise ValueError('Batch approval record exceeds limit')
    if item.get('published_control') != encoded:
        payload = {'embeds': [{'title': 'Batch approval record', 'description': 'The bot uses this record to bind the reviewed host plans to one approval.',
                              'footer': {'text': encoded}}], 'allowed_mentions': {'parse': []}}
        if not item.get('control_message'):
            payload.update(nonce=hashlib.sha256(('control-' + item['id']).encode()).hexdigest()[:24], enforce_nonce=True)
        receipt = q.discord({**config, 'channel_id': item['parent']}, 'PATCH' if item.get('control_message') else 'POST',
                            '/' + item['control_message'] if item.get('control_message') else '', payload)
        if not q.ID.fullmatch(receipt.get('id', '')):
            raise ValueError('Unconfirmed batch approval record')
        item['control_message'] = receipt['id']
        item['published_control'] = encoded
    item['control'] = control
    save(q, config, item)


def coordinate(q, config, item, hosts):
    control = item.setdefault('control', {'kind': 'control', 'batch': item['id'], 'phase': 'collecting', 'scope': item.get('scope', 'all')})
    phase = control['phase']
    if phase == 'collecting':
        if reacted(q, config, item, '❌'):
            control.update(phase='stopped', reason='Canceled during preparation. No updates started.')
        elif any(row['phase'] == 'failed' for row in hosts.values()) or time.time() - item['created'] > 1800:
            control.update(phase='failed', reason='Not every host could prepare a complete plan. No batch was authorized.')
        elif any(row.get('scope', 'all') != item.get('scope', 'all') for row in hosts.values()):
            control.update(phase='failed', reason='A host reported a different update scope. Request a new batch.')
        elif set(hosts) == set(item['nodes']) and all(row['phase'] == 'prepared' for row in hosts.values()):
            roster = {node: {key: hosts[node][key] for key in ('seal', 'count', 'message')} for node in item['nodes']}
            if sum(row['count'] for row in roster.values()) == 0:
                reason = adapters.UNSUPPORTED_SCOPES.get((config['platform'], item.get('scope', 'all')),
                                                         'No eligible updates. Review the exclusions in the host plans.')
                control.update(phase='completed', reason=reason)
            else:
                control.update(phase='proposed', roster=roster, expires=time.time() + 1800, armed=False)
    elif phase == 'proposed':
        if time.time() >= control['expires'] or reacted(q, config, item, '❌'):
            control.update(phase='stopped', reason='The proposal expired or was canceled. No updates started.')
        elif any(node not in hosts or hosts[node]['phase'] != 'prepared' or
                 any(hosts[node][key] != record[key] for key in ('seal', 'count', 'message')) for node, record in control['roster'].items()):
            control.update(phase='failed', reason='A reviewed host plan changed. Request a new batch.')
        elif not control.get('armed'):
            if not reacted(q, config, item, '✅'):
                control['armed'] = True
                control.pop('reason', None)
            else:
                control['reason'] = 'Remove your early ✅, review the plans, then react ✅ again.'
        elif reacted(q, config, item, '✅'):
            actual = q.discord(config, suffix='/' + item['parent'])
            if actual.get('content') != item.get('display') or actual.get('author', {}).get('id') != config['bot_user_id'] or actual.get('webhook_id') or actual.get('embeds'):
                control.update(phase='failed', reason='The displayed proposal changed. No updates started.')
            else:
                control.update(phase='running', approved=time.time(), deadline=time.time() + 6 * 3600)
    if control['phase'] == 'running':
        if time.time() >= control['deadline'] or reacted(q, config, item, '❌') or not reacted(q, config, item, '✅'):
            control.update(phase='stopped', active=None, reason='Pending work stopped. Any current package transaction may finish; inspect host results.')
        elif any(node not in hosts or hosts[node]['seal'] != record['seal'] or hosts[node]['message'] != record['message']
                 for node, record in control['roster'].items()):
            control.update(phase='failed', active=None, reason='A host plan disappeared or changed. Pending work stopped.')
        elif any(row['phase'] in ('failed', 'stopped') for row in hosts.values()):
            control.update(phase='failed', active=None, reason='A host failed or stopped. Remaining updates will not run.')
        else:
            pending = [node for node in item['nodes'] if control['roster'][node]['count'] and hosts[node]['phase'] != 'completed']
            control['active'] = pending[0] if pending else None
            if not pending:
                control.update(phase='completed', reason='All approved actions reported completion. Excluded items were not updated.')
    publish_control(q, config, item, control, hosts)
    if control['phase'] == 'proposed' and not item.get('reactions'):
        for emoji in ('✅', '❌'):
            q.discord(config, 'PUT', '/' + item['parent'] + '/reactions/' + urllib.parse.quote(emoji, safe='') + '/@me')
        item['reactions'] = True
        save(q, config, item)
        if not reacted(q, config, item, '✅'):
            control['armed'] = True
            publish_control(q, config, item, control, hosts)
    return control


def approved(q, config, item, control):
    local = item['local']
    scope = item.get('scope', 'all')
    if (scope not in SCOPES or local['plan'].get('scope', 'all') != scope or control.get('scope', 'all') != scope or
            (scope == 'apps' and any(action['backend'] == 'apt' for action in local['plan']['actions'])) or
            (scope == 'os' and any(action['backend'] != 'apt' for action in local['plan']['actions']))):
        raise backend.Refused('The requested update scope changed or includes an out-of-scope action.')
    if (not config.get('app_updates_enabled') or item['owner'] != config['owner_user_id'] or item['channel'] != config['channel_id'] or
            control.get('phase') != 'running' or control.get('active') != config['node'] or time.time() >= control['deadline'] or
            control.get('batch') != item['id'] or local['code'] != implementation(config) or
            local['seal'] != backend.digest({'plan': local['plan'], 'code': local['code'], 'batch': item['id'], 'nodes': item['nodes'], 'owner': item['owner']}) or
            control.get('roster', {}).get(config['node']) != {'seal': local['seal'], 'count': len(local['plan']['actions']), 'message': local['message']}):
        raise backend.Refused('The batch approval, host order, or reviewed plan changed.')
    actual = q.discord(config, suffix='/' + item['parent'])
    if actual.get('author', {}).get('id') != config['bot_user_id'] or actual.get('webhook_id') or actual.get('embeds'):
        raise backend.Refused('The displayed batch summary changed. No next action will start.')
    if hashlib.sha256(actual.get('content', '').encode()).hexdigest() != control['display']:
        raise AwaitingDisplay('The coordinator is updating the summary')
    if not reacted(q, config, item, '✅') or reacted(q, config, item, '❌'):
        raise backend.Refused('The owner canceled or removed batch approval.')


def poll_locked(q, config, item):
    if item['status'] != 'active':
        return
    if not parent(q, config, item):
        if time.time() - item['created'] > 1800:
            item['status'] = 'closed'
            save(q, config, item)
        return
    local = item['local']
    if local['phase'] == 'waiting':
        local.update(phase='queued', stage='Preparing local package and app plans.')
        save(q, config, item)
        start(config, prepare=True)
    elif local['phase'] == 'queued':
        start(config, prepare=True)
    elif local['phase'] in ('preparing', 'executing'):
        if not unit_active(PREPARE_UNIT if local['phase'] == 'preparing' else EXECUTE_UNIT):
            local.update(phase='failed', stage='Worker interrupted. Outcome unknown; no automatic retry.')
            save(q, config, item)
    publish_local(q, config, item)
    hosts, control = records(q, config, item)
    if config['node'] == item['nodes'][0]:
        control = coordinate(q, config, item, hosts)
    if control and control.get('phase') in TERMINAL:
        if local['phase'] not in ('executing', 'preparing'):
            if local['phase'] not in TERMINAL:
                local.update(phase='stopped', stage='No further work authorized.')
            busy = any(row['phase'] in ('preparing', 'executing', 'approved', 'queued') and
                       int(time.time()) // 60 - row['heartbeat'] < 5 for row in hosts.values())
            save(q, config, item)
            publish_local(q, config, item)
            if config['node'] != item['nodes'][0] or not busy:
                item['status'] = 'closed'
                save(q, config, item)
    elif control and local['phase'] == 'prepared' and control.get('active') == config['node']:
        try:
            approved(q, config, item, control)
            local.update(phase='approved', stage='Approval received. Starting this host.')
            save(q, config, item)
            start(config)
        except AwaitingDisplay:
            pass
        except backend.Refused as error:
            local.update(phase='failed', stage=str(error))
            save(q, config, item)
    elif local['phase'] == 'approved':
        start(config)


def poll(q, config):
    with locked(config):
        item = read(config)
        if item:
            try:
                poll_locked(q, config, item)
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
                item.update(status='closed')
                save(q, config, item)


def local_change(q, config, identifier, **values):
    with locked(config):
        item = read(config)
        if item.get('id') != identifier:
            raise ValueError('Batch identity changed')
        item['local'].update(values)
        save(q, config, item)
        return item


@contextlib.contextmanager
def private_log(path):
    with path.open('a') as output:
        os.chmod(path, 0o600)
        saved_out, saved_err = os.dup(1), os.dup(2)
        try:
            os.dup2(output.fileno(), 1)
            os.dup2(output.fileno(), 2)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                yield
        finally:
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
            os.close(saved_out)
            os.close(saved_err)


def prepare(q, config):
    with locked(config):
        item = read(config)
        if item.get('status') != 'active' or item['local']['phase'] != 'queued':
            return
        item['local']['phase'] = 'preparing'
        save(q, config, item)
    identifier = item['id']
    log = Path(config['state_dir']) / ('batch-' + identifier + '.log')
    try:
        single = Path(config['state_dir']) / 'app-update.json'
        if single.exists() and json.loads(single.read_text()).get('status') != 'closed':
            raise backend.Refused('A single-app update is already active on this host.')
        code = implementation(config)
        with private_log(log):
            plan = adapters.prepare(config, backend, q.versions,
                                    lambda stage: local_change(q, config, identifier, stage=stage), scope=item.get('scope', 'all'))
        if implementation(config) != code:
            raise backend.Refused('The implementation changed while preparing the batch.')
        seal = backend.digest({'plan': plan, 'code': code, 'batch': identifier, 'nodes': item['nodes'], 'owner': item['owner']})
        local_change(q, config, identifier, phase='prepared', plan=plan, code=code, seal=seal,
                     manifest=manifest(config, plan), stage='Ready for the batch review.', results=[])
    except Exception as error:
        with log.open('a') as output:
            os.chmod(log, 0o600)
            traceback.print_exc(file=output)
        local_change(q, config, identifier, phase='failed', stage=str(error) if isinstance(error, backend.Refused) else
                     'Plan preparation failed (' + type(error).__name__ + '). No updates started.')


def execute(q, config):
    with locked(config):
        item = read(config)
        if item.get('status') != 'active' or item['local']['phase'] != 'approved':
            return
        # Persist consumption before any package action. Interrupted batches never replay.
        item['local'].update(phase='executing', results=[])
        save(q, config, item)
    identifier = item['id']
    archive = Path(config['state_dir']) / ('batch-' + identifier)
    archive.mkdir(mode=0o700, exist_ok=True)
    lock_path = backend.BACKUP_ROOT / 'run.lock' if config['platform'] == 'truenas' else Path('/run/lock/lxc-auto-update.lock')
    try:
        with lock_path.open('a') as maintenance, private_log(archive / 'execution.log'):
            fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for index, action in enumerate(item['local']['plan']['actions']):
                for attempt in range(3):
                    _, control = records(q, config, item)
                    try:
                        approved(q, config, item, control or {})
                        break
                    except AwaitingDisplay:
                        if attempt == 2:
                            raise backend.Refused('The batch summary could not be verified. Remaining work stopped.') from None
                        time.sleep(2)
                current = local_change(q, config, identifier, action_started=index,
                                       stage='Updating ' + action['label'].splitlines()[0])
                result = adapters.perform(config, action, backend, q.versions,
                                          lambda stage: local_change(q, config, identifier, stage=stage), archive)
                results = current['local']['results'] + [{'label': action['label'], 'result': result}]
                item = local_change(q, config, identifier, results=results, stage=result)
        local_change(q, config, identifier, phase='completed', stage='All approved local actions completed; see the result file.')
    except Exception as error:
        with (archive / 'execution.log').open('a') as output:
            os.chmod(output.name, 0o600)
            traceback.print_exc(file=output)
        local_change(q, config, identifier, phase='failed', stage=str(error) if isinstance(error, backend.Refused) else
                     'Stopped (' + type(error).__name__ + '). Inspect the private log. Remaining actions were not started.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).with_name('homelab-status')
    if not source.exists():
        source = source.with_suffix('.py')
    q = load('batch_queries', source)
    config = json.loads(args.config.read_text())
    config['_config_path'] = str(args.config.resolve())
    (prepare if args.prepare else execute)(q, config)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Batch worker stopped (' + type(error).__name__ + '). Private details omitted.')
        raise SystemExit(1)
