"""Run with python3 test_web_search.py; no external dependencies required."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile

from web_search import link_items, run_worker, search_items, spotify_link


async def check_queue():
    """Run inside the pinned image with --upstream to test request detachment."""
    import logging
    from types import SimpleNamespace
    import web_search
    from spotdl.download.progress_handler import ProgressHandler
    from spotdl.types.song import Song
    from spotdl.web import routes

    web_search.install_workaround()
    gate = asyncio.Event()
    url = 'https://open.spotify.com/track/2wm3azqIMOl547jRjjtgLU'
    song = Song.from_missing_data(name='Test', artist='Test', artists=['Test'], url=url)
    progress = ProgressHandler(simple_tui=True, web_ui=True)
    progress.progress_tracker.songs = {}

    async def metadata(*args):
        await gate.wait()
        return song

    async def download(value):
        return value, Path('/music/test.mp3')

    client = SimpleNamespace(
        client_id='test', downloader_settings={'output': '/music/{title}.{output-ext}'},
        downloader=SimpleNamespace(progress_handler=progress, settings={}, pool_download=download),
    )
    routes.Client.get_instance = staticmethod(lambda _: client)
    routes.app_state.web_settings = {'web_use_output_dir': True}
    routes.app_state.logger = logging.getLogger('queue-test')
    web_search.lookup = metadata
    signals = SimpleNamespace(client_id='test', song_url=url)
    # A complete HTTP response must not wait for metadata or cancel the job.
    response = [event async for event in web_search.queue_download(signals)]
    assert 'Queued' in str(response)
    task = web_search.DOWNLOAD_TASKS[url]
    assert url in progress.progress_tracker.songs and not task.done()
    response = [event async for event in web_search.queue_download(signals)]
    assert web_search.DOWNLOAD_TASKS[url] is task, 'Duplicate job'
    gate.set()
    await task
    entry = progress.progress_tracker.songs[url]
    assert entry.message == 'Completed' and entry.progress == 100
    assert not web_search.DOWNLOAD_TASKS

    async def failed_download(value):
        return value, None

    client.downloader.pool_download = failed_download
    response = [event async for event in web_search.queue_download(signals)]
    await web_search.DOWNLOAD_TASKS[url]
    assert entry.message.startswith('Error:') and entry.progress == 0
    assert entry.path is None
    print('PASS: immediate queue, detached job, duplicate prevention, completion and visible failure')


async def check():
    assert await run_worker(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"], {"ok": True}
    ) == {"ok": True}
    with tempfile.TemporaryDirectory() as directory:
        pid_file = Path(directory) / "pid"
        command = [sys.executable, "-c",
                   "import os,time,pathlib; "
                   f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); "
                   "time.sleep(60)"]
        task = asyncio.create_task(run_worker(command, {}, timeout=1))
        ticks = 0
        while not task.done():
            await asyncio.sleep(0.05)
            ticks += 1
        try:
            await task
            raise AssertionError("Expected timeout")
        except TimeoutError:
            pass
        assert ticks > 5, "Worker blocked the event loop"
        try:
            os.kill(int(pid_file.read_text()), 0)
            raise AssertionError("Timed-out worker survived")
        except ProcessLookupError:
            pass
        task = asyncio.create_task(run_worker(command, {}))
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        try:
            os.kill(int(pid_file.read_text()), 0)
            raise AssertionError("Cancelled worker survived")
        except ProcessLookupError:
            pass
    assert search_items({"tracks": {"items": []}}) == []
    result = search_items({"tracks": {"items": [{
        "id": "abc", "name": "Song", "artists": [{"name": "Artist"}],
        "album": {"name": "Album", "images": []},
    }]}})[0]
    assert result["url"] == "https://open.spotify.com/track/abc"
    assert result["artists"] == ["Artist"] and result["cover_url"] is None
    identifier = "6xp0NBjMoWgRHKqYPG5Dl3"
    assert spotify_link(f"https://open.spotify.com/intl-de/album/{identifier}?si=abc") == ("album", identifier)
    assert spotify_link("kesha") is None
    for url in ["https://example.com/album/" + identifier,
                "https://open.spotify.com.evil.test/album/" + identifier,
                "file:///etc/passwd", "https://open.spotify.com/album/invalid"]:
        try:
            spotify_link(url)
            raise AssertionError("Invalid link accepted")
        except ValueError:
            pass

    class Client:
        def album(self, value):
            assert value == identifier
            return {"name": "Album", "images": [{"url": "cover"}]}

        def album_tracks(self, value):
            assert value == identifier
            return {"items": [{"id": "a", "name": "One", "artists": [{"name": "Kesha"}]}], "next": "page2"}

        def next(self, page):
            return {"items": [{"id": "b", "name": "Two", "artists": [{"name": "Kesha"}]}], "next": None}

        def playlist_items(self, value):
            return {"items": [{"track": None}, {"track": {
                "id": "a", "name": "One", "artists": [{"name": "Kesha"}],
                "album": {"name": "Album", "images": []},
            }}]}

        def track(self, value):
            return self.playlist_items(value)["items"][1]["track"]

    cards = link_items(Client(), "album", identifier)
    assert len(cards) == 2 and cards[1]["name"] == "Two"
    assert all(card["album_name"] == "Album" and card["cover_url"] == "cover" for card in cards)
    assert len(link_items(Client(), "playlist", identifier)) == 1
    assert len(link_items(Client(), "track", identifier)) == 1


if __name__ == "__main__":
    asyncio.run(check())
    if '--upstream' in sys.argv:
        asyncio.run(check_queue())
    print("PASS: results, responsiveness, worker cleanup, URL validation, album pagination, track and playlist cards")
