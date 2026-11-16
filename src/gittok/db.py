"""SQLite access: connection setup, migrations, and JSON/time helpers."""

import fcntl
import json
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from gittok import private

BUSY_TIMEOUT_MS = 5000


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Settings that live in the connection, not in the file. They read nothing from disk."""
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connect(path: Path | str) -> sqlite3.Connection:
    """A connection to `path`, which is made (private, in WAL mode) when it is missing.

    The switch of a new file to WAL does not wait on the busy timeout: two first connections
    at the same moment can get 'database is locked'. `open_db` takes a lock around it."""
    memory = str(path) == ":memory:"
    if not memory:
        private.make_dir(Path(path).parent)
        private.make_file(path)  # sqlite gives the -wal and -shm files the mode of this file
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        _configure(conn)
        if not memory:
            conn.execute("PRAGMA journal_mode=WAL")
    except BaseException:
        conn.close()
        raise
    return conn


def _migration_files():
    root = resources.files("gittok") / "migrations"
    return sorted((f for f in root.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)


@contextmanager
def _migration_lock(db_file: Path | str):
    """One thread of one process at a time makes and migrates the database file `db_file`."""
    if not str(db_file) or str(db_file) == ":memory:":  # nothing to share
        yield
        return
    with open(f"{db_file}.migrate.lock", "a", opener=private.opener) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _db_file(conn: sqlite3.Connection) -> str:
    return next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")


def migrate(conn: sqlite3.Connection) -> list[str]:
    with _migration_lock(_db_file(conn)):
        return _migrate(conn)


def _statements(script: str):
    """The statements of an SQL script, one at a time (a trigger body stays in one piece)."""
    buf = ""
    parts = script.split(";")
    for part in parts[:-1]:
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            yield buf
            buf = ""
    buf += parts[-1]  # the text after the last ";": a last statement may have none
    if buf.strip():
        yield buf  # not a complete statement: sqlite runs it or reports the error


def _applied(conn: sqlite3.Connection) -> set[str]:
    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if not has_table:
        return set()
    return {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}


def _migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply the migration files that are not applied yet, all in one transaction.

    A file's statements and its row in `schema_migrations` commit together or not at all
    (sqlite DDL is transactional), so a crash or an error part-way leaves the database as it
    was and the next open applies the file again."""
    files = _migration_files()
    if all(f.name in _applied(conn) for f in files):
        return []  # the usual case: no write lock
    applied = []
    with immediate(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
        )
        done = _applied(conn)  # read again: another process may have been first
        for f in files:
            if f.name in done:
                continue
            for statement in _statements(f.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
                (f.name, now_iso()),
            )
            applied.append(f.name)
    return applied


# Database files this process has made ready (WAL mode, schema current): path -> identity of
# the file. A file that was deleted or replaced has a new identity and is made ready again.
_ready: dict[str, tuple] = {}
_ready_guard = threading.Lock()


def _identity(path: str) -> tuple | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_size == 0:
        return None  # a new, empty database file
    return (st.st_dev, st.st_ino, getattr(st, "st_birthtime", None))


def open_db(path: Path | str) -> sqlite3.Connection:
    """A connection to a migrated database.

    The first open of a file in this process makes it, switches it to WAL and migrates it,
    under a file lock (other threads and processes wait). Later opens only connect: WAL mode
    is stored in the file, and the schema of a file does not go back."""
    if str(path) == ":memory:":
        conn = connect(path)
        _migrate(conn)
        return conn
    key = os.path.abspath(path)
    identity = _identity(key)
    with _ready_guard:
        ready = identity is not None and _ready.get(key) == identity
    if ready:
        conn = sqlite3.connect(key, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            return _configure(conn)
        except BaseException:
            conn.close()
            raise
    private.make_dir(Path(key).parent)
    with _migration_lock(key):
        conn = connect(key)
        try:
            _migrate(conn)
        except BaseException:
            conn.close()
            raise
        with _ready_guard:
            _ready[key] = _identity(key)
    return conn


@contextmanager
def session(path: Path | str):
    """`with db.session(path) as conn:` opens the database, commits when the block ends well,
    rolls back when it raises, and always closes the connection."""
    with closing(open_db(path)) as conn, conn:
        yield conn


@contextmanager
def immediate(conn: sqlite3.Connection):
    """Run the block in one BEGIN IMMEDIATE transaction: commit on success, else roll back."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(s: str | None):
    return None if s is None else json.loads(s)


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
