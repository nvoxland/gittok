"""SQLite access: connection setup, migrations, and JSON/time helpers."""

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

LEGACY_DB_NAMES = ("blamescroll.db", "codescroll.db")  # newest first


def _migrate_legacy_files(path: Path) -> None:
    """Product renames: move an old DB (and its side files) to gittok.db, once."""
    if path.name != "gittok.db" or path.exists():
        return
    legacy = next(
        (path.with_name(n) for n in LEGACY_DB_NAMES if path.with_name(n).exists()), None
    )
    if legacy is None:
        return
    # Main file last: if this stops half way, the next call sees no gittok.db and resumes.
    for suffix in ("-wal", "-shm", ".migrate.lock", ""):
        src = legacy.with_name(legacy.name + suffix)
        if src.exists():
            src.rename(path.with_name(path.name + suffix))


def connect(path: Path | str) -> sqlite3.Connection:
    memory = str(path) == ":memory:"
    if not memory:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _migrate_legacy_files(Path(path))
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    # busy_timeout first, so switching to WAL waits instead of failing under contention.
    conn.execute("PRAGMA busy_timeout=5000")
    if not memory:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migration_files():
    root = resources.files("gittok") / "migrations"
    return sorted((f for f in root.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)


@contextmanager
def _migration_lock(conn: sqlite3.Connection):
    """Serialize migrations across threads and processes (executescript is not atomic)."""
    db_file = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    if not db_file:  # in-memory database: nothing to share
        yield
        return
    with open(f"{db_file}.migrate.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def migrate(conn: sqlite3.Connection) -> list[str]:
    with _migration_lock(conn):
        return _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
    )
    conn.commit()
    done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for f in _migration_files():
        if f.name in done:
            continue
        conn.executescript(f.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (f.name, now_iso()),
        )
        conn.commit()
        applied.append(f.name)
    return applied


def open_db(path: Path | str) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


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
