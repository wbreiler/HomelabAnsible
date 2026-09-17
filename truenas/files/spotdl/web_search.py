"""Version-checked spotDL web workaround for blocking Spotify metadata calls."""

import asyncio
import contextlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

SPOTIFY_SETTINGS = {}
DOWNLOAD_TASKS = {}


async def queued_download(client, url):
    """Own the job independently of the browser's request lifetime."""
    from spotdl.utils.web import app_state

    tracker = client.downloader.progress_handler.progress_tracker
    try:
        tracker.songs[url].message = "Loading metadata"
        song = await lookup("track", url)
        tracker.songs[url].song = song
        tracker.songs[url].message = "Queued"
        client.downloader.progress_handler.add_song(song)
        if app_state.web_settings.get("web_use_output_dir", False):
            client.downloader.settings["output"] = client.downloader_settings["output"]
        else:
            from spotdl.utils.config import get_spotdl_path
            client.downloader.settings["output"] = str(
                get_spotdl_path() / "web/sessions" / client.client_id
            )
        _, path = await client.downloader.pool_download(song)
        if path is None:
            raise RuntimeError("Audio download failed. See the container log.")
        tracker.songs[url].path = str(path)
        tracker.songs[url].progress = 100
        tracker.songs[url].message = "Completed"
    except Exception as error:
        tracker.songs[url].message = f"Error: {error}"
        tracker.songs[url].progress = 0
        app_state.logger.error("Download failed for %s: %s", url, error)
    finally:
        DOWNLOAD_TASKS.pop(url, None)


async def queue_download(signals):
    from html import escape
    from spotdl.types.song import Song
    from spotdl.web.routes import Client, SSE

    client = Client.get_instance(signals.client_id)
    try:
        link = spotify_link(signals.song_url)
    except ValueError:
        link = None
    if client is None or not link or link[0] != "track":
        yield SSE.patch_elements('<div id="status" role="alert">Reconnect and select a Spotify track.</div>')
        return
    url = "https://open.spotify.com/track/" + link[1]
    if url not in DOWNLOAD_TASKS:
        tracker = client.downloader.progress_handler.progress_tracker
        song = Song.from_missing_data(name="Loading metadata", artist=url,
                                      artists=[], album_name="", cover_url="", url=url)
        tracker.add(song)
        tracker.songs[url].message = "Queued"
        tracker.songs[url].progress = 0
        tracker.songs[url].path = None
        DOWNLOAD_TASKS[url] = asyncio.create_task(queued_download(client, url))
    yield SSE.patch_elements(
        f'<button id="download-{escape(signals.song_url, quote=True)}" '
        'class="btn btn-primary" disabled>Queued</button>'
    )


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
            "    async for update in gen_download(signals):\n        yield update":
                "    async for update in queue_download(signals):\n        yield update",
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
        module.queue_download = queue_download
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
