#!/usr/bin/python3
"""Publish finished files from the read-only Shared mount without uploading their bytes."""
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time

SHARED = Path("/srv/zipline-media/Shared")
UPLOADS = Path("/var/lib/zipline/uploads")
APP = Path("/opt/zipline")
STATE = APP / "shared-clips.json"
COMPOSE = ["docker", "compose", "--project-directory", str(APP), "exec", "-T"]
MEDIA = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
         ".webm": "video/webm", ".mkv": "video/x-matroska"}
SETTLE_SECONDS = 10


def save(state):
    temp = STATE.with_suffix(".new")
    with temp.open("w", encoding="utf-8") as output:
        json.dump(state, output)
        output.flush()
        os.fsync(output.fileno())
    temp.replace(STATE)


def sql(statement):
    result = subprocess.run(COMPOSE + ["postgresql", "psql", "-XqAt", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=terse",
                                       "-U", "zipline", "-d", "zipline"],
                            input="SET standard_conforming_strings=on;\n" + statement, text=True,
                            stdout=subprocess.PIPE, check=True)
    return result.stdout.strip()


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def signature(source):
    info = source.lstat()
    if stat.S_ISREG(info.st_mode) and info.st_size:
        return [info.st_ino, info.st_size, info.st_mtime_ns]
    return None


def snapshot():
    mount = json.loads(subprocess.check_output(["findmnt", "-J", "-M", str(SHARED),
                                                "-o", "FSTYPE,OPTIONS"]))["filesystems"][0]
    if mount["fstype"] not in ("nfs", "nfs4") or not {"ro", "nosymfollow"} <= set(mount["options"].split(",")):
        raise RuntimeError("Shared requires its read-only NFS mount with nosymfollow")
    # A direct Docker bind drops nosymfollow. The read-only parent bind preserves it on Shared.
    mounts = subprocess.check_output(COMPOSE + ["zipline", "cat", "/proc/self/mountinfo"], text=True)
    if not any(fields[4] == str(SHARED) and {"ro", "nosymfollow"} <= set(fields[5].split(","))
               for fields in (line.split() for line in mounts.splitlines())):
        raise RuntimeError("Docker has lost the protected Shared mount")
    current = {}
    for path in SHARED.iterdir():
        if path.name.startswith(".") or path.suffix.lower() not in MEDIA or not path.name.isprintable():
            continue
        try:
            current[path.name] = signature(path)
        except FileNotFoundError:
            continue
    return {name: sig for name, sig in current.items() if sig}


def remove_entry(source, entry):
    fid = literal(entry["id"])
    # Zipline permits owners to rename public files. Remove only our own symlink.
    stored_name = sql(f'SELECT name FROM "File" WHERE id={fid};')
    for name in {stored_name, entry["storage"]}:
        if name and Path(name).name == name:
            link = UPLOADS / name
            if link.is_symlink() and link.readlink() == source:
                link.unlink()
    sql(f'DELETE FROM "File" WHERE id={fid};')
    (UPLOADS / (".thumbnail." + entry["id"] + ".jpg")).unlink(missing_ok=True)


def complete_movie(source, size):
    """Reject common truncated MP4/MOV copies before the preview decoder reads the first frame."""
    if source.suffix.lower() not in (".mp4", ".m4v", ".mov"):
        return True
    boxes = set()
    with source.open("rb") as media:
        while media.tell() < size:
            start = media.tell()
            header = media.read(8)
            if len(header) != 8:
                return False
            length = int.from_bytes(header[:4], "big")
            boxes.add(header[4:])
            if length == 1:
                length = int.from_bytes(media.read(8), "big")
            elif length == 0:
                length = size - start
            if length < media.tell() - start or start + length > size:
                return False
            media.seek(start + length)
    return {b"moov", b"mdat"} <= boxes


def publish(source, entry, folder, owner):
    # Make the preview from the NAS directly. Zipline's own worker stages full videos.
    if not complete_movie(source, entry["sig"][1]):
        return False
    picture = subprocess.run(COMPOSE + ["zipline", "ffmpeg", "-nostdin", "-v", "error",
        "-protocol_whitelist", "file", "-i", str(source), "-map", "0:v:0", "-frames:v", "1",
        "-vf", "scale=320:-2", "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    if picture.returncode or not picture.stdout.startswith(b"\xff\xd8") or signature(source) != entry["sig"]:
        return False
    storage = entry["storage"]
    link = UPLOADS / storage
    try:
        link.symlink_to(source)
    except FileExistsError:
        if not link.is_symlink() or link.readlink() != source:
            raise RuntimeError("Public file name collision")
    thumb = ".thumbnail." + entry["id"] + ".jpg"
    # Retry safely after interruption before the database transaction.
    with (UPLOADS / (thumb + ".tmp")).open("wb") as output:
        output.write(picture.stdout)
    os.chmod(output.name, 0o644)
    Path(output.name).replace(UPLOADS / thumb)
    fid = literal(entry["id"])
    folder = literal(folder)
    user = '(SELECT id FROM "User" WHERE username=' + literal(owner) + ')'
    if not sql(f"SELECT {user};"):
        raise RuntimeError("Zipline owner is missing")
    sql(f"""BEGIN;
        INSERT INTO "Folder" (id,"updatedAt",name,"userId") VALUES ({folder},now(),'Shared clips',{user})
            ON CONFLICT (id) DO NOTHING;
        INSERT INTO "File" (id,"updatedAt",name,"originalName",size,type,"userId","folderId")
            VALUES ({fid},now(),{literal(storage)},{literal(source.name)},{entry['sig'][1]},
                    {literal(MEDIA[source.suffix.lower()])},{user},{folder})
            ON CONFLICT (id) DO NOTHING;
        INSERT INTO "Thumbnail" (id,"updatedAt",path,"fileId") VALUES ({fid},now(),{literal(thumb)},{fid})
            ON CONFLICT ("fileId") DO NOTHING;
        COMMIT;""")
    return True


def reconcile():
    current = snapshot()  # A mount or scan failure must never look like an empty share.
    state = json.loads(STATE.read_text()) if STATE.exists() else {"folder": secrets.token_hex(16), "files": {}}
    files = state["files"]
    for name, entry in list(files.items()):
        if current.get(name) != entry["sig"]:
            if "id" in entry:
                remove_entry(SHARED / name, entry)
            del files[name]
            save(state)
    owner = json.loads((APP / "admin.json").read_text())["username"]
    for name, sig in current.items():
        if name not in files:
            files[name] = {"sig": sig, "seen": time.time()}
            save(state)
            continue
        entry = files[name]
        if entry.get("published") or time.time() - entry["seen"] < SETTLE_SECONDS:
            continue
        if "id" not in entry:
            entry.update(id=secrets.token_hex(16), storage="shared-" + secrets.token_hex(16) + Path(name).suffix.lower())
            save(state)
        try:
            ready = publish(SHARED / name, entry, state["folder"], owner)
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as error:
            print(f"Skipped one unavailable clip ({type(error).__name__})", file=sys.stderr)
            continue
        if ready:
            entry["published"] = True
            save(state)


if __name__ == "__main__":
    os.umask(0o077)
    with (APP / ".shared-clips.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        reconcile()
