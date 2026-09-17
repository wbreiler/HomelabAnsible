"""Version-checked spotDL web workaround for blocking Spotify metadata calls."""

import asyncio
import contextlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

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


def spotify_link(query):
    parsed = urlsplit(query.strip())
    if not parsed.scheme and not parsed.netloc:
        return None
    match = re.fullmatch(
        r"/(?:intl-[a-zA-Z-]+/)?(track|album|playlist)/([A-Za-z0-9]{22})/?",
        parsed.path,
    )
    if parsed.scheme not in ("http", "https") or parsed.netloc != "open.spotify.com" or not match:
        raise ValueError("Use a direct Spotify track, album, or playlist link.")
    return match.groups()


def link_items(client, kind, identifier):
    if kind == "track":
        tracks = [client.track(identifier)]
    else:
        album = client.album(identifier) if kind == "album" else None
        page = client.album_tracks(identifier) if album else client.playlist_items(identifier)
        tracks = []
        while page:
            for item in page["items"]:
                track = item if album else item.get("track")
                if not track or not track.get("id"):
                    continue
                if album:
                    track = dict(track, album=album)
                tracks.append(track)
            page = client.next(page) if page.get("next") else None
    return search_items({"tracks": {"items": tracks}})


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
            link = spotify_link(payload["query"])
            result = (link_items(SpotifyClient(), *link) if link
                      else search_items(Song.search(payload["query"])))
    print(json.dumps(result))


def install_workaround():
    from spotdl._version import __version__
    from spotdl.web import api, routes

    if __version__ != "4.5.2":
        raise RuntimeError("Review the web workaround before changing spotDL versions")

    replacements = {
        routes: {
            '''    is_valid_url = validate_search_term(signals.search_term)

    if is_valid_url:
        # redirect client to downloads page
        app_state.logger.info(
            f"[{signals.client_id}] Valid URL detected, redirecting to downloads..."
        )
        yield SSE.redirect("/downloads")
        signals.song_url = signals.search_term
        async for update in gen_download(signals):
            yield update

''': "",
            "    songs = get_search_results(signals.search_term)": '''    try:
        songs = await bounded_lookup("search", signals.search_term)
    except (TimeoutError, RuntimeError):
        app_state.logger.warning("Spotify search failed or timed out")
        yield SSE.patch_elements('<div id="search-list" role="alert">Spotify search failed or timed out. Please retry later.</div>')
        return''',
            "        song = Song.from_url(signals.song_url)":
                '        song = await bounded_lookup("track", signals.song_url)',
            '        app_state.logger.error(f"Error downloading! {exception}")':
                '''        app_state.logger.error(f"Error downloading! {exception}")
        from html import escape
        yield SSE.patch_elements(
            f'<button id="download-{escape(signals.song_url, quote=True)}" '
            'class="btn btn-error" role="alert">Download failed. Please retry.</button>'
        )''',
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
