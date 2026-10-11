#!/bin/bash
# LinuxServer executes custom initialization scripts through bash.
exec /lsiopy/bin/python3 - <<'PY'
"""Allow existing large torrent metadata with libtorrent 2.0.13 on startup."""

from importlib.util import find_spec
from pathlib import Path

path = Path(find_spec("deluge.core.torrentmanager").origin)
source = path.read_text()
original = "torrent_info = lt.torrent_info(filepath)"
replacement = "torrent_info = lt.torrent_info(filepath, {'max_buffer_size': 32 * 1024 * 1024})"
if replacement not in source:
    if source.count(original) != 1:
        raise RuntimeError("Pinned Deluge metadata loader changed. Review the compatibility patch.")
    source = source.replace(original, replacement)
    compile(source, str(path), "exec")
    path.write_text(source)
print("Deluge torrent file metadata limit: 32 MiB")
PY
