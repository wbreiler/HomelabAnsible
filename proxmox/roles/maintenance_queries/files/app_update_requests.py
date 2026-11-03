#!/usr/bin/python3
"""Owner-approved app updates, with one durable attempt and one Discord message."""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import traceback
import urllib.error
import urllib.parse


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


backend = load('app_update_backends', Path(__file__).with_name('app_update_backends.py'))
batches = load('maintenance_batches', Path(__file__).with_name('maintenance_batches.py'))
SYNTAX = 'Use `update APP on HOST`, `update all on HOST`, or `update the homelab`. Mention this bot. Review the exact proposal, then ✅ to approve or ❌ to cancel. Batch requests include apps and OS packages; no reboots.'
UNIT = 'homelab-app-update'


def parse(text):
    text = re.sub(r'<@!?[0-9]+>', '', text).strip().lower()
    if text in ('update the homelab', 'upgrade the homelab', 'update homelab', 'upgrade homelab'):
        return ('all', '*')
    match = re.fullmatch(r'(?:update|upgrade) ([a-z0-9][a-z0-9_-]{0,60}(?:/[a-z0-9][a-z0-9_-]{0,60})?) on ([a-z0-9][a-z0-9_-]{0,60})', text)
    return match.groups() if match else None


@contextlib.contextmanager
def locked(config):
    with (Path(config['state_dir']) / 'app-updates.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def state_path(config):
    return Path(config['state_dir']) / 'app-update.json'


def read(config):
    path = state_path(config)
    return json.loads(path.read_text()) if path.exists() else {}


def save(q, config, item):
    q.save(state_path(config), item)
    directory = os.open(config['state_dir'], os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def implementation(config):
    paths = [Path(__file__), Path(__file__).with_name('app_update_backends.py'),
             Path(__file__).with_name('app_versions.py'), Path(config['_config_path'])]
    paths += [path for path in (Path(__file__).with_name('homelab-status'), Path(__file__).with_name('homelab-status.py')) if path.exists()]
    if config['platform'] == 'pve':
        paths += sorted(path for path in backend.APP_ROOT.rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    return backend.digest({str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})


def show(q, config, item, content):
    content = content[:1900] + '\nModel: none · API cost: $0.000000'
    if item.get('delivered') == content:
        return
    item['display'] = content
    save(q, config, item)
    payload = {'content': content, 'embeds': [], 'allowed_mentions': {'parse': []}}
    if not item.get('reply_id'):
        payload.update(nonce=hashlib.sha256(('app-update' + item['id']).encode()).hexdigest()[:24], enforce_nonce=True,
                       message_reference={'message_id': item['id'], 'fail_if_not_exists': False})
        receipt = q.discord(config, 'POST', payload=payload)
        if receipt.get('channel_id') != config['channel_id'] or not q.ID.fullmatch(receipt.get('id', '')):
            raise ValueError('Unconfirmed update reply')
        item['reply_id'] = receipt['id']
        save(q, config, item)
    receipt = q.discord(config, 'PATCH', '/' + item['reply_id'],
                        {key: payload[key] for key in ('content', 'embeds', 'allowed_mentions')})
    if receipt.get('id') != item['reply_id'] or receipt.get('content') != content:
        raise ValueError('Unconfirmed update message')
    item['delivered'] = content
    save(q, config, item)


def reacted(q, config, item, emoji):
    suffix = '/' + item['reply_id'] + '/reactions/' + urllib.parse.quote(emoji, safe='')
    users = q.discord(config, suffix=suffix + '?type=0&after=' + str(int(config['owner_user_id']) - 1) + '&limit=1')
    return any(user.get('id') == config['owner_user_id'] and not user.get('bot') for user in users)


def proposal(config, item):
    return ('⏸ **Approve one app update**\n' + config['node'] + ' · ' + item['plan']['label'] + '\n' +
            item['plan']['effect'] + f'\nExpires <t:{int(item["expires"])}:R>.\n✅ Approve once · ❌ Cancel')


def valid(q, config, item):
    if (not config.get('app_updates_enabled') or item.get('owner') != config['owner_user_id'] or item.get('channel') != config['channel_id'] or
            item.get('node') != config['node'] or time.time() >= item['expires'] or
            item['plan_hash'] != backend.digest(item['plan']) or item['code_hash'] != implementation(config)):
        raise backend.Refused('The approval expired, or its target, code, or configuration changed. Request a new proposal.')
    displayed = q.discord(config, suffix='/' + item['reply_id'])
    if (displayed.get('author', {}).get('id') != config['bot_user_id'] or displayed.get('webhook_id') or
            displayed.get('channel_id') != config['channel_id'] or displayed.get('content') != item['display'] or
            displayed.get('embeds')):
        raise backend.Refused('The displayed proposal changed. No update started.')
    if not reacted(q, config, item, '✅') or reacted(q, config, item, '❌'):
        raise backend.Refused('Approval was removed or canceled. No update started.')


def request(q, config, message):
    selected = parse(message['content'])
    if selected and selected[0] == 'all':
        return batches.request(q, config, message, selected[1])
    if not selected or selected[1] != config['node']:
        return
    if batches.active(config):
        q.discord(config, 'POST', payload={'content': 'A maintenance batch is active on ' + config['node'] + '. Finish or cancel it first.',
                  'allowed_mentions': {'parse': []}, 'nonce': 'busy-' + message['id'], 'enforce_nonce': True})
        return
    with locked(config):
        previous = read(config)
        if previous.get('id') == message['id']:
            return
        if previous and previous['status'] != 'closed':
            q.discord(config, 'POST', payload={'content': 'An app update request is already active on ' + config['node'] + '. Finish or cancel its proposal first.',
                'allowed_mentions': {'parse': []}, 'message_reference': {'message_id': message['id'], 'fail_if_not_exists': False},
                'nonce': 'busy-' + message['id'], 'enforce_nonce': True})
            return
        if previous:
            q.save(Path(config['state_dir']) / ('app-update-' + previous['id'] + '.json'), previous)
        item = {'id': message['id'], 'owner': config['owner_user_id'], 'channel': config['channel_id'],
                'node': config['node'], 'status': 'preparing', 'created': time.time()}
        save(q, config, item)
        show(q, config, item, '⏳ **Working…**\nPreparing an app update proposal. No update is authorized. This can take 2–5 minutes.')
        try:
            plan = backend.prepare(config, selected[0], q.versions)
            item.update(plan=plan, plan_hash=backend.digest(plan), code_hash=implementation(config),
                        expires=time.time() + 1800, status='proposed')
        except Exception as error:
            with (Path(config['state_dir']) / ('app-update-' + item['id'] + '.log')).open('a') as output:
                os.chmod(output.name, 0o600)
                traceback.print_exc(file=output)
            item.update(status='closed', outcome=str(error) if isinstance(error, backend.Refused) else
                        'Proposal preparation failed (' + type(error).__name__ + '). No update started. Inspect the private worker log.')
        save(q, config, item)
        render(q, config, item)


def render(q, config, item):
    if item.get('notification_lost'):
        return
    status = item['status']
    if status == 'proposed':
        show(q, config, item, proposal(config, item))
        if not item.get('reactions_added'):
            for emoji in ('✅', '❌'):
                q.discord(config, 'PUT', '/' + item['reply_id'] + '/reactions/' + urllib.parse.quote(emoji, safe='') + '/@me')
            item['reactions_added'] = True
            save(q, config, item)
        if not item.get('armed') and not reacted(q, config, item, '✅'):
            item['armed'] = True
            save(q, config, item)
    elif status in ('approved', 'executing'):
        show(q, config, item, '⏳ **Working…**\n' + config['node'] + ' · ' + item['plan']['label'] + '\n' +
             item.get('stage', 'Approval received. Waiting for the app update worker.') +
             '\nOne attempt only. No automatic retry.' + f'\nStarted <t:{int(item.get("started", item["created"]))}:R>.')
    elif status == 'closed':
        show(q, config, item, '🏁 **App update request finished**\n' + config['node'] + '\n' + item['outcome'])


def start(config):
    # Transient service survives the query timeout, and has no restart policy or timer.
    subprocess.run(['systemd-run', '--quiet', '--collect', '--unit=' + UNIT,
                    '--property=Type=exec', '--property=UMask=0077', '--property=TimeoutStartSec=infinity',
                    '/usr/bin/python3', str(Path(__file__).resolve()), '--execute', '--config', config['_config_path']],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def advance(q, config, item):
    status = item['status']
    if status == 'preparing':
        item.update(status='closed', outcome='Proposal preparation was interrupted. No update started. Request a new proposal.')
    elif status == 'proposed':
        render(q, config, item)
        if time.time() >= item['expires'] or reacted(q, config, item, '❌'):
            item.update(status='closed', outcome='The proposal expired or was canceled. No update started.')
        elif item.get('armed') and reacted(q, config, item, '✅'):
            try:
                valid(q, config, item)
                item.update(status='approved', approved_at=time.time())
            except backend.Refused as error:
                item.update(status='closed', outcome=str(error))
    elif status == 'approved' and time.time() >= item['expires']:
        item.update(status='closed', outcome='The approval expired before execution. No update started.')
    elif status == 'executing':
        active = subprocess.run(['systemctl', 'is-active', '--quiet', UNIT + '.service'], timeout=15).returncode == 0
        if not active:
            item.update(status='closed', outcome='The update worker stopped unexpectedly. The outcome is unknown. Inspect the app before another attempt.')
    save(q, config, item)
    render(q, config, item)
    if item['status'] == 'approved':
        start(config)


def poll(q, config):
    with locked(config):
        item = read(config)
        if not item:
            return
        try:
            advance(q, config, item)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            # A deleted approval never becomes a replacement approval message.
            if item['status'] != 'executing':
                item.update(status='closed', outcome='The proposal message was deleted. No new attempt is authorized.')
            item['notification_lost'] = True
            save(q, config, item)


def execute(q, config):
    with locked(config):
        item = read(config)
        if item.get('status') != 'approved':
            return
        try:
            valid(q, config, item)
        except Exception as error:
            item.update(status='closed', outcome=str(error) if isinstance(error, backend.Refused) else
                        'Approval could not be verified. No update started.')
            save(q, config, item)
            return
        # Durably consume approval before any backup, image pull, or service change.
        item.update(status='executing', started=time.time())
        save(q, config, item)
    def progress(stage):
        with locked(config):
            item['stage'] = stage
            save(q, config, item)
            try:
                render(q, config, item)
            except Exception:
                pass  # Discord failure must not interrupt an approved transaction.
    lock_path = Path('/run/lock/lxc-auto-update.lock') if config['platform'] == 'pve' else backend.BACKUP_ROOT / 'run.lock'
    log = Path(config['state_dir']) / ('app-update-' + item['id'] + '.log')
    try:
        with lock_path.open('a') as maintenance, log.open('a') as output:
            os.chmod(log, 0o600)
            fcntl.flock(maintenance, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                # Child updater output can contain private configuration; keep it out of journald.
                saved_out, saved_err = os.dup(1), os.dup(2)
                try:
                    os.dup2(output.fileno(), 1)
                    os.dup2(output.fileno(), 2)
                    outcome = backend.perform(config, item['plan'], q.versions, progress)
                finally:
                    os.dup2(saved_out, 1)
                    os.dup2(saved_err, 2)
                    os.close(saved_out)
                    os.close(saved_err)
    except BlockingIOError:
        outcome = 'Another maintenance or backup run holds the lock. No update started. Request a new proposal after it finishes.'
    except Exception as error:
        with log.open('a') as output:
            os.chmod(log, 0o600)
            traceback.print_exc(file=output)
        outcome = str(error) if isinstance(error, backend.Refused) else 'Update stopped (' + type(error).__name__ + '). Inspect the private update log and app health. No automatic retry.'
    with locked(config):
        item.update(status='closed', outcome=outcome)
        save(q, config, item)
        render(q, config, item)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', required=True)
    args = parser.parse_args()
    source = Path(__file__).with_name('homelab-status')
    if not source.exists():
        source = source.with_suffix('.py')
    q = load('homelab_queries', source)
    config = json.loads(args.config.read_text())
    config['_config_path'] = str(args.config.resolve())
    execute(q, config)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('App update worker stopped (' + type(error).__name__ + '). Private details omitted.')
        raise SystemExit(1)
