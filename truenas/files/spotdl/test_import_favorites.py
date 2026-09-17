"""Run with python3 test_import_favorites.py."""
from import_favorites import choose_track, normalized, seconds
import import_favorites
import json
from pathlib import Path
import tempfile

row = {'Song': 'Song!', 'Artist': 'Artist & Guest', 'Album': 'Album', 'Duration': '3:20'}
track = {'id': 'one', 'name': 'Song!', 'artists': [{'name': 'Artist'}, {'name': 'Guest'}],
         'album': {'name': 'Album'}, 'duration_ms': 200000}
assert choose_track(row, [track]) == track
assert normalized('Beyoncé') == normalized('Beyonce')
assert seconds('1:02:03') == 3723
for candidates in [[], [dict(track, name='Song! (Live)')],
                   [dict(track, duration_ms=240000)],
                   [dict(track, artists=[{'name': 'Someone Else'}])],
                   [dict(track, artists=[{'name': 'Artist'}])],
                   [track, dict(track, id='two', duration_ms=202000)]]:
    try:
        choose_track(row, candidates)
        raise AssertionError('Accepted an uncertain match')
    except ValueError:
        pass
assert choose_track(row, [dict(track, id='two', album={'name': 'Other'}), track]) == track
assert choose_track(row, [track, dict(track, id='regional-copy')]) == track
with tempfile.TemporaryDirectory() as directory:
    manifest = Path(directory) / 'manifest.json'
    manifest.write_text(json.dumps([row]))
    output = Path(directory) / 'track.mp3'
    output.write_bytes(b'test')
    calls = []

    def fake_job(row, directory):
        calls.append(row)
        return {'status': 'complete', 'path': str(output)}

    import_favorites.job = fake_job
    import_favorites.main(manifest)
    import_favorites.main(manifest)
    assert len(calls) == 1, 'Resume repeated a completed download'
    manifest.write_text(json.dumps([dict(row, Song='Different')]))
    try:
        import_favorites.main(manifest)
        raise AssertionError('Accepted changed manifest with old checkpoint')
    except ValueError:
        pass
print('PASS: matching, ambiguity rejection, completed-file resume, manifest guard')
