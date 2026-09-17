"""Resumable, two-worker CSV import. Personal input and results stay outside Git."""

import argparse
import concurrent.futures
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import unicodedata


def normalized(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.findall(r'\w+', ''.join(c for c in value if not unicodedata.combining(c))))


def seconds(value):
    parts = [int(part) for part in value.split(':')]
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def choose_track(row, tracks):
    def artists(value):
        return set(normalized(value).split()) - {'and', 'feat', 'featuring', 'ft', 'with'}

    candidates = [track for track in tracks
                  if normalized(track['name']) == normalized(row['Song'])
                  and track.get('artists')
                  and artists(' '.join(artist['name'] for artist in track['artists'])) == artists(row['Artist'])
                  and abs(track['duration_ms'] / 1000 - seconds(row['Duration'])) <= 5]
    album = normalized(re.sub(r' - (Single|EP)$', '', row['Album'], flags=re.I))
    exact_album = [track for track in candidates if normalized(track['album']['name']) == album]
    candidates = exact_album or candidates
    # Spotify can expose the same album recording under several regional IDs.
    unique = {}
    for track in candidates:
        recording = (normalized(track['album']['name']), track['duration_ms'],
                     track.get('explicit'), tuple(sorted(artists(' '.join(a['name'] for a in track['artists'])))))
        unique.setdefault(recording, track)
    if len(unique) != 1:
        raise ValueError(f'Needs review: {len(unique)} matching Spotify recordings')
    return next(iter(unique.values()))


def worker(row):
    from spotdl.download.downloader import Downloader
    from spotdl.types.song import Song
    from spotdl.utils.config import create_settings
    from spotdl.utils.spotify import SpotifyClient

    settings, download_settings, _ = create_settings(argparse.Namespace(
        config=False, threads=1, lyrics=[], overwrite='skip', simple_tui=True,
        output='/music/{artists} - {title}.{output-ext}',
    ))
    SpotifyClient.init(**settings)
    url = row.get('url')
    if not url:
        response = Song.search(row['Artist'] + ' - ' + row['Song'])
        match = choose_track(row, response['tracks']['items'])
        url = 'https://open.spotify.com/track/' + match['id']
    song = Song.from_url(url)
    downloader = Downloader(settings=download_settings)
    downloader.progress_handler.set_songs([song])
    _, path = downloader.search_and_download(song)
    if path is None or not path.is_file():
        raise RuntimeError('Download failed; see the per-track log')
    return {'status': 'complete', 'url': url, 'path': str(path), 'bytes': path.stat().st_size}


def job(row, directory):
    key = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:20]
    log_path = directory / (key + '.log')
    with log_path.open('wb') as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), '--worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, start_new_session=True,
        )
        try:
            output, _ = process.communicate(json.dumps(row).encode(), timeout=240)
            result = json.loads(output) if process.returncode == 0 else {
                'status': 'failed', 'reason': 'Worker failed; see the per-track log',
            }
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            result = {'status': 'failed', 'reason': 'Exceeded four-minute per-track limit'}
    return dict(result, log=str(log_path), song=row['Song'], artist=row['Artist'], album=row['Album'])


def main(manifest):
    os.umask(0o077)
    directory = manifest.parent
    with (directory / 'import.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rows = json.loads(manifest.read_text())
        state_path = directory / 'status.json'
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
        previous = json.loads(state_path.read_text()) if state_path.exists() else {}
        if previous and previous.get('manifest_sha256') != manifest_hash:
            raise ValueError('Manifest changed; use a new import directory')
        results = previous.get('results', {})
        pending = [(str(i), row) for i, row in enumerate(rows)
                   if str(i) not in results or
                   (results[str(i)]['status'] == 'complete' and not Path(results[str(i)]['path']).is_file())]

        def save():
            state = {'manifest_sha256': manifest_hash, 'total': len(rows), 'finished': len(results),
                     'complete': sum(r['status'] == 'complete' for r in results.values()),
                     'failed': sum(r['status'] != 'complete' for r in results.values()),
                     'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'results': results}
            temporary = state_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, indent=2))
            temporary.replace(state_path)
            print(f"{state['finished']}/{state['total']}: {state['complete']} complete, {state['failed']} need review", flush=True)

        save()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(job, row, directory): index for index, row in pending}
            for future in concurrent.futures.as_completed(futures):
                results[futures[future]] = future.result()
                save()


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        row = json.load(sys.stdin)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result = worker(row)
        except ValueError as error:
            result = {'status': 'review', 'reason': str(error)}
        print(json.dumps(result))
    else:
        main(Path(sys.argv[1]).resolve())
