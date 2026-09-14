"""Run as root inside loki-nash. Test 720h retention using isolated /tmp storage.

The test binds only loopback ports 13100 and 19095. It writes one synthetic
31-day-old chunk, accelerates compaction/deletion, and verifies file removal.
It stops its test process but preserves its temporary evidence directory.
Production data and the production Loki process are never modified.
"""

import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request

root = pathlib.Path(tempfile.mkdtemp(prefix='loki-retention-check-'))
config = pathlib.Path('/etc/loki/config.yml').read_text()
assert 'retention_period: 720h' in config, 'This check expects 30-day production retention'
config = config.replace('/var/lib/loki', str(root / 'data'))
config = config.replace('http_listen_address: 0.0.0.0', 'http_listen_address: 127.0.0.1')
config = config.replace('http_listen_port: 3100', 'http_listen_port: 13100\n  grpc_listen_address: 127.0.0.1\n  grpc_listen_port: 19095')
config = config.replace('"2026-09-14"', '"2020-01-01"')
config = config.replace('compaction_interval: 10m', 'compaction_interval: 5s')
config = config.replace('retention_delete_delay: 2h', 'retention_delete_delay: 1s')
config = config.replace('max_query_lookback: 720h', 'max_query_lookback: 0s\n  reject_old_samples: false')
(root / 'config.yml').write_text(config)
url = 'http://127.0.0.1:13100'
process = None
log = (root / 'process.log').open('w')

def start():
    global process
    process = subprocess.Popen(['/usr/bin/loki', '-config.file=' + str(root / 'config.yml')], stdout=log, stderr=log)
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError('Test Loki exited. See ' + str(root))
        try:
            with urllib.request.urlopen(url + '/ready', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError('Test Loki did not become ready')

try:
    start()
    data = {'streams': [{'stream': {'host': 'retention-test', 'job': 'verification'},
                         'values': [[str(time.time_ns() - 31 * 86400 * 10**9), 'synthetic retention check']]}]}
    request = urllib.request.Request(url + '/loki/api/v1/push', data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 204
    with urllib.request.urlopen(urllib.request.Request(url + '/flush', data=b''), timeout=30):
        pass
    process.terminate()
    process.wait(timeout=60)
    chunks = list((root / 'data/chunks/fake').glob('*'))
    assert chunks, 'No persisted test chunks'
    print('Persisted synthetic 31-day-old chunks:', len(chunks), flush=True)
    start()
    for _ in range(180):
        if all(not chunk.exists() for chunk in chunks):
            print('PASS: Compactor deleted the synthetic chunks using 720h retention. Test directory:', root, flush=True)
            break
        time.sleep(1)
    else:
        raise RuntimeError('Chunks not deleted within test deadline. See ' + str(root))
finally:
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=60)
    log.close()
