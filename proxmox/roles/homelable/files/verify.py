"""Run inside the LXC: /opt/homelable/venv/bin/python verify.py [port]."""
import json
import re
from pathlib import Path
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = f'http://127.0.0.1:{int(sys.argv[1]) if len(sys.argv) > 1 else 3000}'

def request(path, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    body = json.dumps(data).encode() if data is not None else None
    with urlopen(Request(base + path, data=body, headers=headers), timeout=15) as response:
        return response.read()

assert json.loads(request('/api/v1/health'))['status'] == 'ok'
with urlopen('http://127.0.0.1:8000/openapi.json', timeout=15) as response:
    assert json.load(response)['info']['version'] == Path('/opt/homelable/.ansible-version').read_text().strip()
page = request('/').decode()
assert '<html' in page.lower()
assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
assert assets, 'No frontend assets referenced'
for asset in assets:
    assert request(asset), f'Empty frontend asset: {asset}'
try:
    request('/api/v1/auth/me')
except HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError('Unauthenticated access was accepted')
password = Path('/root/homelable-admin-password')
assert password.stat().st_mode & 0o777 == 0o600
credentials = {'username': 'admin', 'password': password.read_text().strip()}
token = json.loads(request('/api/v1/auth/login', credentials))['access_token']
assert json.loads(request('/api/v1/auth/me', token=token))['subject'] == 'admin'
with sqlite3.connect('file:/var/lib/homelable/homelab.db?mode=ro', uri=True) as database:
    assert database.execute('PRAGMA integrity_check').fetchone() == ('ok',)
print('PASS: frontend, health, login, access control, private credentials, SQLite integrity')
