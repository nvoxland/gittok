import re
import sqlite3

import pytest

from codescroll import db

SPEC_TABLES = {
    "repos", "groups", "repo_groups", "git_signals", "runs", "cards", "card_features",
    "assets", "events", "rewards", "weights", "rules", "personas", "mascots", "srs",
    "notifications",
}  # fmt: skip


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_migrate_creates_all_spec_tables(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    assert SPEC_TABLES <= table_names(conn)


def test_migrate_twice_applies_nothing_second_time(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    first = db.migrate(conn)
    assert first == ["0001_init.sql", "0002_story_key_unique.sql"]
    assert db.migrate(conn) == []
    assert conn.execute("SELECT name FROM schema_migrations").fetchall()[0]["name"] == first[0]


def test_wal_mode_on_file_db(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_memory_db_works():
    conn = db.open_db(":memory:")
    assert "repos" in table_names(conn)


def test_foreign_keys_enforced(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
            " story_key, created_at) VALUES ('c','nope',1,'s','f','p','t','{}','k','now')"
        )


def test_runs_status_check(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','bogus','now')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','open','now')")


def test_dumps_loads_roundtrip_unicode():
    obj = {"b": 1, "a": "héllo ✨"}
    s = db.dumps(obj)
    assert s == '{"a":"héllo ✨","b":1}'
    assert db.loads(s) == obj
    assert db.loads(None) is None


def test_now_iso_format():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", db.now_iso())


def test_connect_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "x.db"
    db.connect(p).close()
    assert p.exists()


def test_card_cascade_and_events_survive(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','open','now')")
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
        " story_key, created_at) VALUES ('c','r',1,'s','f','p','t','{}','k','now')"
    )
    conn.execute("INSERT INTO card_features VALUES ('c','tone','x')")
    conn.execute("INSERT INTO events(card_id, type, ts, received_at) VALUES ('c','view',1,'now')")
    conn.execute("DELETE FROM cards WHERE id='c'")
    assert conn.execute("SELECT count(*) FROM card_features").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
