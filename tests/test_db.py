import re
import sqlite3

import pytest

from codescroll import db

SPEC_TABLES = {
    "repos", "groups", "repo_groups", "git_signals", "runs", "cards", "card_features",
    "assets", "events", "rewards", "weights", "rules", "personas", "mascots", "srs",
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
        "0001_init.sql",
        "0002_story_key_unique.sql",
        "0003_learning_indexes.sql",
        "0004_social.sql",
        "0005_prefs.sql",
        "0006_drop_saves.sql",
        "0007_stories.sql",
        "0008_leads.sql",
        "0009_story_variants.sql",
        "0010_saved_cards.sql",
        "0011_candidates.sql",
        "0012_knowledge.sql",
        "0013_lead_keys.sql",
        "0015_requests.sql",
    ]
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


def test_stories_migration_backfills_from_cards(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','open','now')")
    spec = '{"sources": [{"repo": "r", "commit": "abc"}]}'
    for cid, key in (("c1", "k1"), ("c2", "k2")):
        conn.execute(
            "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
            " story_key, created_at) VALUES (?,'r',1,'s','f','p','t',?,?,'2026-01-01T00:00:00Z')",
            (cid, spec, key),
        )
    conn.execute("INSERT INTO rewards(card_id, reward, computed_at) VALUES ('c1', 0.7, 'now')")
    conn.execute("INSERT INTO rewards(card_id, reward, computed_at) VALUES ('c1', 0.2, 'now')")
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES ('c1','like',1,'{\"on\":true}','now')"
    )
    conn.execute("DROP TABLE stories")
    conn.executescript(
        next(f for f in db._migration_files() if f.name == "0007_stories.sql").read_text(
            encoding="utf-8"
        )
    )

    rows = {r["story_key"]: r for r in conn.execute("SELECT * FROM stories")}
    assert set(rows) == {"k1", "k2"}
    assert rows["k1"]["repo"] == "r" and rows["k1"]["story_type"] == "s"
    assert db.loads(rows["k1"]["sources"]) == [{"repo": "r", "commit": "abc"}]
    assert rows["k1"]["cards_made"] == 1
    assert rows["k1"]["best_reward"] == 0.7 and rows["k1"]["liked"] == 1
    assert rows["k2"]["best_reward"] is None and rows["k2"]["liked"] == 0


def test_story_variants_migration_backfills_formats_and_allows_second_format(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','open','now')")
    for cid, key, fmt in (("c1", "k1", "meme"), ("c2", "k1", "thread"), ("c3", "k2", "quiz")):
        conn.execute(
            "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
            " story_key, created_at) VALUES (?,'r',1,'s',?,'p','t','{}',?,'2026-01-01T00:00:00Z')",
            (cid, fmt, key),
        )
    conn.execute("DELETE FROM stories")
    conn.execute("INSERT INTO stories(story_key, story_type, first_card_at, last_card_at) "
                 "VALUES ('k1','s','a','a'), ('k2','s','a','a'), ('k3','s','a','a')")  # fmt: skip
    conn.execute("DROP INDEX IF EXISTS idx_cards_story_key_format_unique")
    conn.execute("ALTER TABLE stories DROP COLUMN formats")
    conn.executescript(
        next(f for f in db._migration_files() if f.name == "0009_story_variants.sql").read_text(
            encoding="utf-8"
        )
    )

    rows = {r["story_key"]: db.loads(r["formats"]) for r in conn.execute("SELECT * FROM stories")}
    assert rows == {"k1": ["meme", "thread"], "k2": ["quiz"], "k3": []}
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
            " story_key, created_at) VALUES ('c4','r',1,'s','meme','p','t','{}','k1','now')"
        )


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


def test_drop_saves_migration_deletes_save_events_only(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)
    conn.execute("DELETE FROM schema_migrations WHERE name = '0006_drop_saves.sql'")
    for t in ("save", "like"):
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES ('c', ?, 1, '{}', 'x')",
            (t,),
        )
    conn.commit()
    assert db.migrate(conn) == ["0006_drop_saves.sql"]
    assert [r[0] for r in conn.execute("SELECT type FROM events")] == ["like"]


def test_saved_cards_migration_backfills_latest_on_saves(tmp_path):
    conn = db.open_db(tmp_path / "x.db")
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', '/r')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r','open','now')")
    for cid, key in (("c1", "k1"), ("c2", "k2"), ("c3", "k3")):
        conn.execute(
            "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
            " story_key, created_at) VALUES (?,'r',1,'s','text','p','t','{}',?,'2026-01-01')",
            (cid, key),
        )
    for cid, ts, on in (
        ("c1", 1000, True),
        ("c2", 1000, True),
        ("c2", 2000, False),  # latest is off
        ("c3", 3000, True),
        ("c_gone", 4000, True),  # no card
    ):
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'save', ?, ?, 'x')",
            (cid, ts, db.dumps({"on": on})),
        )
    conn.execute("DROP TABLE saved_cards")
    conn.executescript(
        next(f for f in db._migration_files() if f.name == "0010_saved_cards.sql").read_text(
            encoding="utf-8"
        )
    )

    rows = {r["card_id"]: r["saved_ts"] for r in conn.execute("SELECT * FROM saved_cards")}
    assert rows == {"c1": 1000, "c3": 3000}
    assert conn.execute("SELECT saved_at FROM saved_cards WHERE card_id='c1'").fetchone()[0] == (
        "1970-01-01T00:00:01Z"
    )
