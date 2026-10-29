#!/usr/bin/env python3
"""Reject a migration source whose directory entry a service can replace."""

from pathlib import Path
import stat
import sys


def validate_source(path):
    source = Path(path)
    if not source.is_absolute() or ".." in source.parts or source == Path("/"):
        raise ValueError("The migration source must be an absolute game directory")
    if not stat.S_ISDIR(source.lstat().st_mode):
        raise ValueError("The migration source must be a real directory, not a symlink")
    for parent in source.parents:
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError(f"Migration source ancestor must be a protected root-owned directory: {parent}")


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("Usage: check_migration_source.py SOURCE")
        validate_source(sys.argv[1])
    except (OSError, ValueError) as error:
        sys.exit(str(error))
