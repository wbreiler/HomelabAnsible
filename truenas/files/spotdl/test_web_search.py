"""Run with python3 test_web_search.py; no external dependencies required."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile

from web_search import run_worker, search_items


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


if __name__ == "__main__":
    asyncio.run(check())
    print("PASS: results, responsiveness, timeout cleanup, cancellation cleanup")
