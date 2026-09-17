"""Version-checked spotDL web workaround for blocking Spotify metadata calls."""

import asyncio
import contextlib
import json
from pathlib import Path
import sys

SPOTIFY_SETTINGS = {}


async def run_worker(command, payload, timeout=30):
    process = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(json.dumps(payload).encode()), timeout
        )
        if process.returncode:
            raise RuntimeError("Spotify lookup failed. Please retry later.")
        return json.loads(stdout)
    except asyncio.TimeoutError as error:
        raise TimeoutError("Spotify lookup exceeded 30 seconds. Please retry later.") from error
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.wait()


async def lookup(operation, query):
    from spotdl.types.song import Song

    result = await run_worker(
        [sys.executable, str(Path(__file__).resolve()), "--lookup"],
        {"operation": operation, "query": query, "settings": SPOTIFY_SETTINGS},
    )
    if operation == "track":
        return Song.from_dict(result)
    return [Song.from_missing_data(**item) for item in result]


def search_items(response):
    # Search cards need only the metadata already present in the search response.
    return [
        {
            "name": track["name"],
            "artists": [artist["name"] for artist in track["artists"]],
            "album_name": track["album"]["name"],
            "cover_url": next(iter(track["album"].get("images", [])), {}).get("url"),
            "explicit": track.get("explicit", False),
            "url": "https://open.spotify.com/track/" + track["id"],
        }
        for track in response["tracks"]["items"]
    ]


def worker():
    from spotdl.types.song import Song
    from spotdl.utils.spotify import SpotifyClient

    payload = json.load(sys.stdin)
    # Dependencies can print diagnostics; reserve stdout for the JSON result.
    with contextlib.redirect_stdout(sys.stderr):
        SpotifyClient.init(**payload["settings"])
        if payload["operation"] == "track":
            result = Song.from_url(payload["query"]).json
        else:
            result = search_items(Song.search(payload["query"]))
    print(json.dumps(result))


def install_workaround():
    from spotdl._version import __version__
    from spotdl.web import api, routes

    if __version__ != "4.5.2":
        raise RuntimeError("Review the web workaround before changing spotDL versions")

    replacements = {
        routes: {
            "    songs = get_search_results(signals.search_term)": '''    try:
        songs = await bounded_lookup("search", signals.search_term)
    except (TimeoutError, RuntimeError):
        app_state.logger.warning("Spotify search failed or timed out")
        yield SSE.patch_elements('<div id="search-list" role="alert">Spotify search failed or timed out. Please retry later.</div>')
        return''',
            "        song = Song.from_url(signals.song_url)":
                '        song = await bounded_lookup("track", signals.song_url)',
            "            yield update\n\n    songs":
                "            yield update\n        return\n\n    songs",
        },
        api: {
            "def query_search(query: str)": "async def query_search(query: str)",
            "    return get_search_results(query)":
                '    return await bounded_lookup("search", query)',
            "        song = Song.from_url(url)":
                '        song = await bounded_lookup("track", url)',
        },
    }
    # Modify module code in memory. The pinned image stays unchanged.
    for module, changes in replacements.items():
        source = Path(module.__file__).read_text()
        # Apply the redirect fix before replacing the following search statement.
        for old, new in reversed(list(changes.items())):
            if source.count(old) != 1:
                raise RuntimeError(f"Unexpected upstream code in {module.__name__}")
            source = source.replace(old, new)
        module.bounded_lookup = lookup
        exec(compile(source, module.__file__, "exec"), module.__dict__)


if __name__ == "__main__":
    if sys.argv[1:] == ["--lookup"]:
        worker()
    else:
        from spotdl.console.entry_point import console_entry_point
        from spotdl.utils.arguments import parse_arguments
        from spotdl.utils.config import create_settings

        SPOTIFY_SETTINGS = create_settings(parse_arguments())[0]
        install_workaround()
        console_entry_point()
