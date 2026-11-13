import re
import sqlite3

import pytest

from gittok import db

SPEC_TABLES = {
    "repos", "groups", "repo_groups", "git_signals", "runs", "cards", "card_features",
    "assets", "events", "rewards", "model_weights", "rules", "personas", "mascots", "srs",
    "notifications", "stories", "leads", "saved_cards",
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
    assert first == [
        "0001_schema.sql",
        "0002_pair_requests.sql",
        "0003_one_learner.sql",
        "0004_learning_fixes.sql",
    ]
    assert db.migrate(conn) == []
    names = [r["name"] for r in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]
    assert names == first


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


def test_rewards_unique_per_impression_and_events_type_index(tmp_path):
    import sqlite3

    import pytest

    conn = db.open_db(tmp_path / "x.db")
    idx = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_events_type_ts" in idx
    ins = "INSERT INTO rewards (card_id, impression_event_id, reward, computed_at) VALUES (?,?,?,?)"
    conn.execute(ins, ("c1", 7, 0.5, "2026-01-01T00:00:00Z"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("c1", 7, 0.6, "2026-01-01T00:00:00Z"))


def test_social_tables_and_notification_dedup_key_is_unique(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    assert "story_views" in table_names(conn)
    ins = "INSERT INTO notifications(kind, text, created_at, dedup_key) VALUES ('k','t','now',?)"
    conn.execute(ins, ("a",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, ("a",))
    conn.execute(ins, (None,))
    conn.execute(ins, (None,))


def test_concurrent_open_db_migrates_once_without_errors(tmp_path):
    import threading

    path = tmp_path / "race.db"
    errors = []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait()
            db.open_db(path).close()
        except Exception as e:  # noqa: BLE001 - collect anything
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    conn = db.connect(path)
    names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations")]
    assert len(names) == len(set(names)) == len(db._migration_files())


class _FakeMigration:
    def __init__(self, name, sql):
        self.name, self._sql = name, sql

    def read_text(self, encoding=None):
        return self._sql


def test_a_migration_that_fails_part_way_leaves_nothing_and_can_run_again(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    bad = _FakeMigration("0001_schema.sql", "CREATE TABLE a (x);\nCREATE TABLE b (y);\nNOT SQL;\n")
    monkeypatch.setattr(db, "_migration_files", lambda: [bad])
    with pytest.raises(sqlite3.Error):
        db.open_db(path)
    conn = db.connect(path)
    assert table_names(conn) <= {"schema_migrations"}  # no half-made schema
    if "schema_migrations" in table_names(conn):
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0
    conn.close()
    monkeypatch.undo()
    conn = db.open_db(path)  # the real schema applies to the same file
    assert SPEC_TABLES <= table_names(conn)
    assert [r[0] for r in conn.execute("SELECT name FROM schema_migrations")] == [
        f.name for f in db._migration_files()
    ]
    conn.close()


def test_migration_statements_and_the_version_row_commit_together(tmp_path, monkeypatch):
    """The version row is written in the transaction of the schema: a failure there rolls
    the tables back too."""
    path = tmp_path / "x.db"
    good = _FakeMigration("0001_schema.sql", "CREATE TABLE a (x);\n")
    monkeypatch.setattr(db, "_migration_files", lambda: [good])

    def boom():
        raise RuntimeError("crash before the version row")

    monkeypatch.setattr(db, "now_iso", boom)
    with pytest.raises(RuntimeError):
        db.open_db(path)
    conn = db.connect(path)
    assert "a" not in table_names(conn)
    conn.close()


def test_migration_script_with_a_trigger_body_is_split_correctly(tmp_path, monkeypatch):
    sql = (
        "CREATE TABLE a (x);\nCREATE TABLE log (x); -- note; with a semicolon\n"
        "CREATE TRIGGER t AFTER INSERT ON a BEGIN\n  INSERT INTO log VALUES (new.x);\n"
        "  INSERT INTO log VALUES ('a;b');\nEND;\n"
    )
    monkeypatch.setattr(db, "_migration_files", lambda: [_FakeMigration("0001_schema.sql", sql)])
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO a VALUES (1)")
    assert conn.execute("SELECT count(*) FROM log").fetchone()[0] == 2
    conn.close()


def test_open_db_migrates_once_per_process_and_path(tmp_path, monkeypatch):
    calls = []
    real = db._migrate
    monkeypatch.setattr(db, "_migrate", lambda conn: calls.append(1) or real(conn))
    path = tmp_path / "x.db"
    for _ in range(5):
        db.open_db(path).close()
    assert len(calls) == 1
    db.open_db(tmp_path / "y.db").close()
    assert len(calls) == 2


def test_later_opens_do_not_take_the_migration_lock(tmp_path, monkeypatch):
    path = tmp_path / "x.db"
    db.open_db(path).close()
    monkeypatch.setattr(db, "_migration_lock", lambda p: pytest.fail("lock taken again"))
    conn = db.open_db(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


def test_open_db_migrates_again_when_the_file_is_deleted_or_replaced(tmp_path):
    path = tmp_path / "x.db"
    db.open_db(path).close()
    for suffix in ("", "-wal", "-shm"):
        (tmp_path / f"x.db{suffix}").unlink(missing_ok=True)
    conn = db.open_db(path)
    assert SPEC_TABLES <= table_names(conn)
    conn.close()
    other = tmp_path / "other.db"
    sqlite3.connect(other).close()  # an empty database file
    other.touch()
    other.replace(path)
    for suffix in ("-wal", "-shm"):
        (tmp_path / f"x.db{suffix}").unlink(missing_ok=True)
    conn = db.open_db(path)
    assert SPEC_TABLES <= table_names(conn)
    conn.close()


def test_concurrent_open_db_many_rounds(tmp_path):
    """The first opens of one file race on the switch to WAL; every round must be clean."""
    import threading

    for n in range(25):
        path = tmp_path / f"race{n}.db"
        errors = []
        barrier = threading.Barrier(8)

        def worker(path=path, errors=errors, barrier=barrier):
            try:
                barrier.wait()
                db.open_db(path).close()
            except Exception as e:  # noqa: BLE001 - collect anything
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == [], f"round {n}"


def test_a_new_data_dir_and_database_are_private(tmp_path):
    import os
    import stat

    old = os.umask(0o022)
    try:
        path = tmp_path / "data" / "gittok.db"
        conn = db.open_db(path)
        conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
        conn.commit()
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        for f in path.parent.iterdir():  # the database and its -wal / -shm files
            assert stat.S_IMODE(f.stat().st_mode) == 0o600, f.name
        conn.close()
    finally:
        os.umask(old)


def test_an_existing_data_dir_keeps_its_mode(tmp_path):
    import os
    import stat

    old = os.umask(0o022)
    try:
        d = tmp_path / "mine"
        d.mkdir(mode=0o755)
        db.open_db(d / "gittok.db").close()
        assert stat.S_IMODE(d.stat().st_mode) == 0o755
        assert stat.S_IMODE((d / "gittok.db").stat().st_mode) == 0o600
    finally:
        os.umask(old)


def test_one_learner_migration(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    names = table_names(conn)
    assert "requests" not in names and "weights" not in names and "model_weights" in names

    def cols(t):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}

    assert {"weight", "signal", "features"} <= cols("rewards")
    assert "disliked" in cols("stories")
    assert {"mean", "precision", "n", "updated_at"} <= cols("model_weights")
    for t in ("knowledge", "knowledge_symbols"):
        assert not {"knew_it", "teach_more"} & cols(t)
