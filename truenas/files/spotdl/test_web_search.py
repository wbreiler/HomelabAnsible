"""Run with python3 test_web_search.py; no external dependencies required."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile

from web_search import link_items, run_worker, search_items, spotify_link


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
    print("PASS: results, responsiveness, worker cleanup, URL validation, album pagination, track and playlist cards")
