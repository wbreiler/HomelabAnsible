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
import uuid

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
    return scan_tree(SHARED)


def scan_tree(root):
    files = {}
    folders = []
    pending = [root]
    device = root.stat().st_dev
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path.name.startswith(".") or not path.name.isprintable():
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if info.st_dev != device:
                continue
            relative = str(path.relative_to(root))
            if stat.S_ISDIR(info.st_mode):
                folders.append(relative)
                pending.append(path)
            elif stat.S_ISREG(info.st_mode) and info.st_size and path.suffix.lower() in MEDIA:
                files[relative] = [info.st_ino, info.st_size, info.st_mtime_ns]
    return files, sorted(folders)


def folder_id(root_id, path):
    if path == Path("."):
        return root_id
    return uuid.uuid5(uuid.UUID(root_id), str(path)).hex


def folder_inserts(root_id, paths, user):
    statements = []
    for path in sorted(paths, key=lambda p: len(p.parts)):
        is_root = path == Path(".")
        name = "Shared clips" if is_root else path.name
        parent = "NULL" if is_root else literal(folder_id(root_id, path.parent))
        statements.append(f'''INSERT INTO "Folder" (id,"updatedAt",name,"userId","parentId")
            VALUES ({literal(folder_id(root_id, path))},now(),{literal(name)},{user},{parent})
            ON CONFLICT (id) DO NOTHING;''')
    return "\n".join(statements)


def sync_folders(state, folders, user):
    root_id = state["folder"]
    current = {Path(name) for name in folders}
    old = {Path(name) for name in state.get("directories", [])}
    statements = [folder_inserts(root_id, current | {Path(".")}, user)]
    for path in sorted(old - current, key=lambda p: len(p.parts), reverse=True):
        fid = literal(folder_id(root_id, path))
        # Keep folders that the dashboard owner has repurposed or populated.
        statements.append(f'''DELETE FROM "Folder" WHERE id={fid} AND "userId"={user}
            AND "parentId"={literal(folder_id(root_id, path.parent))}
            AND name={literal(path.name)}
            AND NOT EXISTS (SELECT 1 FROM "File" WHERE "folderId"={fid})
            AND NOT EXISTS (SELECT 1 FROM "Folder" WHERE "parentId"={fid});''')
    sql("BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;")
    state["directories"] = folders
    save(state)


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


def publish(source, entry, root_id, user):
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
    parents = source.relative_to(SHARED).parents
    folder = literal(folder_id(root_id, parents[0]))
    sql(f"""BEGIN;
        {folder_inserts(root_id, parents, user)}
        INSERT INTO "File" (id,"updatedAt",name,"originalName",size,type,"userId","folderId")
            VALUES ({fid},now(),{literal(storage)},{literal(source.name)},{entry['sig'][1]},
                    {literal(MEDIA[source.suffix.lower()])},{user},{folder})
            ON CONFLICT (id) DO NOTHING;
        INSERT INTO "Thumbnail" (id,"updatedAt",path,"fileId") VALUES ({fid},now(),{literal(thumb)},{fid})
            ON CONFLICT ("fileId") DO NOTHING;
        COMMIT;""")
    return True


def preview_catalog(files):
    """Only this catalog, never Zipline credentials, is mounted in the encoder."""
    directory = APP / "preview-catalog"
    directory.mkdir(mode=0o755, exist_ok=True)
    # The publisher normally has umask 077. The encoder runs as nobody.
    directory.chmod(0o755)
    existing = {entry["id"] for entry in files.values() if entry.get("published")}
    if existing:
        rows = sql('SELECT id FROM "File" WHERE id IN (' + ",".join(map(literal, existing)) + ');')
        existing = set(rows.splitlines())
    catalog = {entry["storage"]: name for name, entry in files.items()
               if "storage" in entry and (not entry.get("published") or entry["id"] in existing)}
    path = directory / "clips.json"
    data = json.dumps(catalog, sort_keys=True)
    if not path.exists() or path.read_text() != data:
        tmp = path.with_suffix(".new")
        tmp.write_text(data)
        tmp.chmod(0o644)
        tmp.replace(path)


def ready_previews():
    result = subprocess.run(COMPOSE + ["discord-preview", "ls", "-1", "/dev/shm"],
                            text=True, stdout=subprocess.PIPE, check=True, timeout=15)
    return set(result.stdout.splitlines())


def reconcile():
    current, folders = snapshot()  # A mount or scan failure must never look like an empty share.
    state = json.loads(STATE.read_text()) if STATE.exists() else {"folder": secrets.token_hex(16), "files": {}}
    files = state["files"]
    for name, entry in list(files.items()):
        if current.get(name) != entry["sig"]:
            if "id" in entry:
                remove_entry(SHARED / name, entry)
            del files[name]
            save(state)
    owner = json.loads((APP / "admin.json").read_text())["username"]
    user = None
    structure_changed = folders != state.get("directories")
    if structure_changed or any(not entry.get("published") for entry in files.values()):
        owner_id = sql('SELECT id FROM "User" WHERE username=' + literal(owner) + ';')
        if not owner_id:
            raise RuntimeError("Zipline owner is missing")
        user = literal(owner_id)
    if structure_changed:
        sync_folders(state, folders, user)
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
    preview_catalog(files)
    pending = [(name, entry) for name, entry in files.items()
               if "storage" in entry and not entry.get("published")]
    if not pending:
        return
    prepared = ready_previews()
    for name, entry in pending:
        if entry["storage"].rsplit(".", 1)[0] + ".mp4" not in prepared:
            continue
        try:
            ready = publish(SHARED / name, entry, state["folder"], user)
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
