#!/usr/bin/env python3
"""Verify a freshly emitted journal marker from every expected host in Loki.

Usage: verify_logging.py http://LOKI:3100 MARKER host [host ...]
Emit the same MARKER with logger on each host first. This reads no log bodies
other than the requested marker and prints only host names and label keys.
"""

import json
import sys
import time
import urllib.parse
import urllib.request


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    url, marker, *hosts = sys.argv[1:]
    params = urllib.parse.urlencode({
        "query": '{host=~".+"} |= ' + json.dumps(marker),
        "start": str(time.time_ns() - 600 * 10**9),
        "limit": "5000",
    })
    request = urllib.request.Request(
        url.rstrip('/') + '/loki/api/v1/query_range?' + params,
        headers={'X-Loki-Response-Encoding-Flags': 'categorize-labels'},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    assert result['status'] == 'success', result['status']
    streams = [entry['stream'] for entry in result['data']['result']]
    found = {stream['host'] for stream in streams}
    assert set(hosts) <= found, f'Missing hosts: {sorted(set(hosts) - found)}'
    keys = {key for stream in streams for key in stream}
    assert keys <= {'host', 'job', 'unit'}, f'Unexpected labels: {sorted(keys)}'
    assert all(stream.get('job') == 'systemd-journal' for stream in streams), 'Journal job label was replaced'
    print(f'PASS: {len(found)} hosts, labels {sorted(keys)}')
    print(', '.join(sorted(found)))


if __name__ == '__main__':
    main()
