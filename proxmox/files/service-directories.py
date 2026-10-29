#!/usr/bin/python3
"""Create service directories without following service-controlled paths."""
import json
import os
from pathlib import PurePosixPath
import pwd
import stat
import subprocess
import sys


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
UNPRIVILEGED_DIRECTORY = """
import os, stat, sys
path, mode = sys.argv[1], int(sys.argv[2], 8)
changed = not os.path.isdir(path)
os.makedirs(path, mode=mode, exist_ok=True)
if stat.S_IMODE(os.stat(path).st_mode) != mode:
    os.chmod(path, mode)
    changed = True
print('changed' if changed else 'unchanged')
"""


class ServiceOwnedParent(PermissionError):
    """The remaining path requires service privileges instead of root."""


def prepare(parent_fd, parts, uid, gid, mode):
    """Walk from a trusted directory descriptor, then configure only the leaf."""
    current = os.dup(parent_fd)
    changed = False
    try:
        for index, part in enumerate(parts):
            parent = os.fstat(current)
            if parent.st_uid == uid and parent.st_uid != os.geteuid():
                raise ServiceOwnedParent("Continue through service-owned ancestors only after dropping privileges")
            if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
                raise PermissionError("Service directory ancestors must be root-owned and not writable by other users")
            try:
                os.mkdir(part, 0o755, dir_fd=current)
                changed = True
            except FileExistsError:
                pass
            child = os.open(part, DIRECTORY_FLAGS, dir_fd=current)
            os.close(current)
            current = child
            if index == len(parts) - 1:
                existing = os.fstat(current)
                if (existing.st_uid, existing.st_gid) != (uid, gid):
                    os.fchown(current, uid, gid)
                    changed = True
                if stat.S_IMODE(existing.st_mode) != mode:
                    os.fchmod(current, mode)
                    changed = True
        return changed
    finally:
        os.close(current)


def main():
    user, home, encoded = sys.argv[1:]
    if os.geteuid() != 0:
        raise PermissionError("Service directory bootstrap requires root")
    directories = json.loads(encoded)
    paths = {}
    for entry in directories:
        path = PurePosixPath(entry["path"])
        if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
            raise ValueError("Service directories require absolute paths below a trusted parent")
        paths[path.parts[1:]] = int(entry["mode"], 8)
    changed = False
    try:
        account = pwd.getpwnam(user)
    except KeyError:
        subprocess.run([
            "/usr/sbin/useradd", "--system", "--home-dir", home,
            "--shell", "/usr/sbin/nologin", user,
        ], check=True)
        account = pwd.getpwnam(user)
        changed = True
    if account.pw_uid == 0:
        raise PermissionError("Services must use a non-root account")
    root = os.open("/", DIRECTORY_FLAGS)
    try:
        for parts, mode in paths.items():
            try:
                changed = prepare(root, parts, account.pw_uid, account.pw_gid, mode) or changed
            except ServiceOwnedParent:
                result = subprocess.run(
                    [sys.executable, "-c", UNPRIVILEGED_DIRECTORY,
                     str(PurePosixPath("/", *parts)), oct(mode)],
                    user=account.pw_uid, group=account.pw_gid,
                    extra_groups=os.getgrouplist(user, account.pw_gid),
                    check=True, capture_output=True, text=True,
                )
                changed = result.stdout.strip() == "changed" or changed
    finally:
        os.close(root)
    print("changed" if changed else "unchanged")


if __name__ == "__main__":
    main()
