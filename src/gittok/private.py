"""Files only the user may read: the data directory, the database, the logs, the LAN token.

A directory GitTok makes gets mode 0700 and a file it makes gets mode 0600, whatever the umask.
A directory that is already there keeps its mode: the user (or a shared volume) chose it.
"""

from __future__ import annotations

import os
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def make_dir(path: Path | str) -> Path:
    """Make `path` and its missing parents, each with mode 0700. Existing ones are not changed."""
    path = Path(path)
    missing = []
    p = path
    while not p.exists() and p != p.parent:
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        try:
            d.mkdir(mode=DIR_MODE)
        except FileExistsError:  # another thread or process made it first
            continue
        os.chmod(d, DIR_MODE)  # mkdir applies the umask; a umask like 0277 must not lock us out
    return path


def opener(path, flags: int) -> int:
    """For `open(..., opener=private.opener)`: a file this call creates gets mode 0600."""
    return os.open(path, flags, FILE_MODE)


def make_file(path: Path | str) -> None:
    """Make sure `path` is a file only the user can read or write. Creates it empty if missing;
    a file that is there has the group and other bits removed. Never raises on a file of
    another owner."""
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, FILE_MODE))
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077:
            os.chmod(path, mode & 0o700)
    except OSError:
        pass
