#!/usr/bin/env python3
"""Validate and extract server packs without following archive paths or links."""

import fnmatch
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
from urllib.parse import urlsplit
import zipfile


def destination(root, name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError(f"Invalid pack path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.rstrip("/").split("/")):
        raise ValueError(f"Unsafe pack path: {name!r}")
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Pack path escapes staging: {name!r}")
    return target


def https_url(url):
    if not isinstance(url, str) or any(character in url for character in "\r\n\0"):
        raise ValueError("Invalid pack download URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("Pack downloads require an HTTPS URL without credentials")
    return url


def members(archive, root):
    entries = archive.infolist()
    for entry in entries:
        destination(root, entry.orig_filename)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"Archive links and special files are unsupported: {entry.filename!r}")
        if entry.orig_filename != entry.filename:
            raise ValueError("Invalid archive member name")
    return entries


def extract(archive, root, entries, patterns=()):
    for entry in entries:
        if patterns and not any(fnmatch.fnmatchcase(entry.filename, pattern) for pattern in patterns):
            continue
        target = destination(root, entry.filename)
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644 | ((entry.external_attr >> 16) & 0o111))


def assemble(archive, root, entries):
    index_entry = next((entry for entry in entries if entry.filename == "modrinth.index.json"), None)
    if index_entry is None:
        extract(archive, root, entries)
        return
    index = json.loads(archive.read(index_entry))
    if not isinstance(index, dict) or not isinstance(index.get("dependencies", {}), dict):
        raise ValueError("Invalid Modrinth index")
    files = index.get("files")
    if not isinstance(files, list):
        raise ValueError("The Modrinth index must contain a files array")
    downloads = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("env", {}), dict):
            raise ValueError("Invalid Modrinth file entry")
        if entry.get("env", {}).get("server") == "unsupported":
            continue
        target = destination(root, entry.get("path"))
        urls = entry.get("downloads")
        if not isinstance(urls, list) or not urls:
            raise ValueError("A Modrinth file has no download URL")
        downloads.append((target, https_url(urls[0])))
    dependencies = index.get("dependencies", {})
    print(f"mc_version: {dependencies.get('minecraft', '?')}", file=sys.stderr)
    for loader in ("forge", "neoforge", "fabric-loader", "quilt-loader"):
        if loader in dependencies:
            print(f"loader: {loader}, loader_version: {dependencies[loader]}", file=sys.stderr)
    for target, url in downloads:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-q", "--proto", "=https", "--proto-redir", "=https", "-fsSL",
                        "-o", str(target), "--", url], check=True)
    for prefix in ("overrides/", "server-overrides/"):
        for entry in entries:
            if entry.filename.startswith(prefix) and entry.filename != prefix:
                name = entry.filename[len(prefix):]
                target = destination(root, name)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o644 | ((entry.external_attr >> 16) & 0o111))


def main():
    if len(sys.argv) < 4 or sys.argv[1] not in ("extract", "assemble"):
        raise ValueError("Usage: pack_archive.py extract|assemble PACK DEST [PATTERN ...]")
    operation, pack, target, *patterns = sys.argv[1:]
    root = Path(target)
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(pack) as archive:
        entries = members(archive, root)
        if operation == "assemble":
            assemble(archive, root, entries)
        else:
            extract(archive, root, entries, patterns)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        sys.exit(f"Invalid server pack: {error}")
