import json
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from blamescroll import db, gc, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(days_ago: float) -> int:
    return int((NOW - timedelta(days=days_ago)).timestamp() * 1000)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn(cfg):
    c = db.open_db(cfg.settings.data_dir / "blamescroll.db")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-01-01T00:00:00Z')"
    )
    yield c
    c.close()


def add_card(conn, cfg, created_days_ago=100, status="ready") -> str:
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}))
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now=iso(created_days_ago))
    conn.execute("UPDATE cards SET status = ? WHERE id = ?", (status, cid))
    asset_dir = cfg.settings.data_dir / "assets" / cid
    asset_dir.mkdir(parents=True)
    (asset_dir / "a.png").write_bytes(b"x")
    conn.execute(
        "INSERT INTO assets(card_id, kind, path) VALUES (?, 'image', ?)", (cid, f"{cid}/a.png")
    )
    conn.commit()
    return cid


def seen(conn, cid, days_ago, reward=0.5, like=None) -> int:
    """An impression `days_ago` days ago with a reward row; optional like toggle."""
    cur = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (cid, ms(days_ago), iso(days_ago)),
    )
    imp = cur.lastrowid
    if like is not None:
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, 'like', ?, ?, ?)",
            (cid, ms(days_ago) + 1000, json.dumps({"on": like}), iso(days_ago)),
        )
    conn.execute(
        "INSERT INTO rewards(card_id, impression_event_id, reward, computed_at) "
        "VALUES (?, ?, ?, ?)",
        (cid, imp, reward, iso(days_ago - 0.01)),  # computed a quarter hour after the impression
    )
    conn.commit()
    return imp


def bury(conn, cfg, n=20, days_ago=1) -> None:
    """`n` other cards shown (no reward yet, so gc keeps them) after every older impression."""
    for i in range(n):
        later = add_card(conn, cfg)
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{}', ?)",
            (later, ms(days_ago) + i, iso(days_ago)),
        )
    conn.commit()


def exists(conn, cid) -> bool:
    return conn.execute("SELECT 1 FROM cards WHERE id = ?", (cid,)).fetchone() is not None


def count(conn, sql, *args) -> int:
    return conn.execute(sql, args).fetchone()[0]


def test_seen_unliked_card_past_window_is_deleted_with_assets_and_srs(conn, cfg):
    cid = add_card(conn, cfg)
    seen(conn, cid, 20)
    conn.execute(  # review is far off: not protected
        "INSERT INTO srs(card_id, interval_days, due_at) VALUES (?, 1, ?)", (cid, iso(-200))
    )
    conn.execute(
        "INSERT INTO notifications(kind, text, card_id, created_at) VALUES ('k', 't', ?, ?)",
        (cid, iso(1)),
    )
    conn.commit()
    fresh = add_card(conn, cfg)  # fewer than 20 cards came after it: kept
    seen(conn, fresh, 0.5)
    bury(conn, cfg, 20, days_ago=1)

    res = gc.collect(conn, cfg, NOW)

    assert res["seen"] == 1
    assert not exists(conn, cid)
    assert exists(conn, fresh)
    assert not (cfg.settings.data_dir / "assets" / cid).exists()
    assert (cfg.settings.data_dir / "assets" / fresh).exists()
    assert count(conn, "SELECT COUNT(*) FROM card_features WHERE card_id = ?", cid) == 0
    assert count(conn, "SELECT COUNT(*) FROM assets WHERE card_id = ?", cid) == 0
    assert count(conn, "SELECT COUNT(*) FROM srs WHERE card_id = ?", cid) == 0
    assert conn.execute("SELECT card_id FROM notifications").fetchone()[0] is None
    # memory is kept
    assert count(conn, "SELECT COUNT(*) FROM rewards WHERE card_id = ?", cid) == 1
    assert count(conn, "SELECT COUNT(*) FROM stories") == 22


def test_liked_card_kept_until_liked_window(conn, cfg):
    a = add_card(conn, cfg)
    seen(conn, a, 20, like=True)
    b = add_card(conn, cfg)
    seen(conn, b, 100, like=True)
    c = add_card(conn, cfg)  # liked, then unliked: treated as unliked
    seen(conn, c, 20, like=True)
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, 'like', ?, ?, ?)",
        (c, ms(19), json.dumps({"on": False}), iso(19)),
    )
    conn.commit()
    bury(conn, cfg)

    res = gc.collect(conn, cfg, NOW)

    assert exists(conn, a)
    assert not exists(conn, b)
    assert not exists(conn, c)
    assert (res["seen"], res["liked"]) == (1, 1)


def test_later_impressions_count_distinct_cards_after_the_last_impression(conn, cfg):
    target = add_card(conn, cfg)
    seen(conn, target, 3)
    early = add_card(conn, cfg)  # shown before the target: does not count
    seen(conn, early, 4)
    bury(conn, cfg, 18)
    twice = add_card(conn, cfg)  # many impressions, one card
    for i in range(5):
        conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{}', ?)",
            (twice, ms(1) + i, iso(1)),
        )
    conn.commit()

    gc.collect(conn, cfg, NOW)

    assert exists(conn, target)  # 18 + 1 = 19 distinct later cards


def test_seen_card_deleted_after_20_later_cards(conn, cfg):
    target = add_card(conn, cfg)
    seen(conn, target, 3)
    bury(conn, cfg, 19)
    assert gc.collect(conn, cfg, NOW)["seen"] == 0
    assert exists(conn, target)
    bury(conn, cfg, 1)
    assert gc.collect(conn, cfg, NOW)["seen"] == 1
    assert not exists(conn, target)


def test_saved_card_never_collected(conn, cfg):
    saved = add_card(conn, cfg, created_days_ago=400)
    seen(conn, saved, 300)
    liked = add_card(conn, cfg, created_days_ago=400)
    seen(conn, liked, 300, like=True)
    stale = add_card(conn, cfg, created_days_ago=400)
    conn.executemany(
        "INSERT INTO saved_cards(card_id, saved_at, saved_ts) VALUES (?, ?, ?)",
        [(saved, iso(299), ms(299)), (liked, iso(299), ms(299)), (stale, iso(299), ms(299))],
    )
    conn.commit()
    bury(conn, cfg, 30)

    gc.collect(conn, cfg, NOW)

    assert exists(conn, saved) and exists(conn, liked) and exists(conn, stale)
    assert count(conn, "SELECT COUNT(*) FROM saved_cards") == 3


def test_seen_card_without_reward_kept(conn, cfg):
    cid = add_card(conn, cfg)
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (cid, ms(3), iso(3)),
    )
    conn.commit()
    bury(conn, cfg, 25)

    assert gc.collect(conn, cfg, NOW)["seen"] == 0
    assert exists(conn, cid)


def test_srs_due_card_kept(conn, cfg):
    due = add_card(conn, cfg)
    seen(conn, due, 20)
    conn.execute(
        "INSERT INTO srs(card_id, interval_days, due_at) VALUES (?, 1, ?)", (due, iso(-10))
    )
    far = add_card(conn, cfg)
    seen(conn, far, 20)
    conn.execute(
        "INSERT INTO srs(card_id, interval_days, due_at) VALUES (?, 1, ?)", (far, iso(-200))
    )
    done = add_card(conn, cfg)
    seen(conn, done, 20)
    conn.execute(
        "INSERT INTO srs(card_id, interval_days, due_at, mastered) VALUES (?, 1, ?, 1)",
        (done, iso(-10)),
    )
    conn.commit()
    bury(conn, cfg)

    gc.collect(conn, cfg, NOW)

    assert exists(conn, due)
    assert not exists(conn, far)
    assert not exists(conn, done)


def test_unseen_stale_card_deleted(conn, cfg):
    stale = add_card(conn, cfg, created_days_ago=60)
    fresh = add_card(conn, cfg, created_days_ago=10)
    failed_old = add_card(conn, cfg, created_days_ago=10, status="render_failed")
    failed_new = add_card(conn, cfg, created_days_ago=2, status="render_failed")
    impressed = add_card(conn, cfg, created_days_ago=60)
    conn.execute(  # impressed but no reward yet: not unseen, not seen
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (impressed, ms(1), iso(1)),
    )
    conn.commit()

    res = gc.collect(conn, cfg, NOW)

    assert not exists(conn, stale)
    assert exists(conn, fresh)
    assert not exists(conn, failed_old)
    assert exists(conn, failed_new)
    assert exists(conn, impressed)
    assert (res["unseen"], res["failed"]) == (1, 1)


def test_events_pruned_only_when_rewarded(conn, cfg):
    cid = add_card(conn, cfg)
    imp = seen(conn, cid, 120, like=True)
    old_dwell = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, 'dwell', ?, '{}', ?)",
        (cid, ms(120) + 500, iso(120)),
    ).lastrowid
    # old impression with no reward: kept
    lonely = add_card(conn, cfg)
    lonely_imp = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (lonely, ms(120), iso(120)),
    ).lastrowid
    # rewarded card, but an old event after the newest rewarded impression: kept
    late = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, 'dwell', ?, '{}', ?)",
        (cid, ms(100), iso(100)),
    ).lastrowid
    # recent rewarded impression: kept
    recent = add_card(conn, cfg)
    recent_imp = seen(conn, recent, 10)
    conn.commit()

    res = gc.collect(conn, cfg, NOW)

    left = {r[0] for r in conn.execute("SELECT id FROM events")}
    assert imp not in left and old_dwell not in left
    assert {lonely_imp, late, recent_imp} <= left
    assert res["events"] >= 2


def test_run_files_pruned(conn, cfg):
    runs_dir = cfg.settings.data_dir / "runs"
    for rid, status, finished in [
        ("old", "finished", iso(40)),
        ("new", "finished", iso(5)),
        ("open", "open", None),
        ("exp", "expired", iso(40)),
    ]:
        conn.execute(
            "INSERT INTO runs(id, status, started_at, finished_at) VALUES (?, ?, ?, ?)",
            (rid, status, iso(41), finished),
        )
        (runs_dir / rid).mkdir(parents=True)
        (runs_dir / rid / "submission-1.json").write_text("[]")
    conn.commit()

    res = gc.collect(conn, cfg, NOW)

    assert res["run_files"] == 2
    assert not (runs_dir / "old").exists() and not (runs_dir / "exp").exists()
    assert (runs_dir / "new").exists() and (runs_dir / "open").exists()
    assert count(conn, "SELECT COUNT(*) FROM runs") == 5  # rows stay


def test_social_rows_pruned(conn, cfg):
    conn.executemany(
        "INSERT INTO story_views(repo, sha, seen_at) VALUES (?, ?, ?)",
        [("a", "1", iso(40)), ("a", "2", iso(5))],
    )
    conn.executemany(
        "INSERT INTO notifications(kind, text, created_at, read_at) VALUES ('k', 't', ?, ?)",
        [(iso(50), iso(40)), (iso(50), iso(5)), (iso(50), None)],
    )
    conn.commit()

    res = gc.collect(conn, cfg, NOW)

    assert (res["story_views"], res["notifications"]) == (1, 1)
    assert count(conn, "SELECT COUNT(*) FROM story_views") == 1
    assert count(conn, "SELECT COUNT(*) FROM notifications") == 2


def snapshot(conn, cfg):
    tables = ["cards", "events", "rewards", "srs", "notifications", "story_views", "assets"]
    rows = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in tables}
    files = sorted(str(p) for p in cfg.settings.data_dir.rglob("*"))
    return rows, [f for f in files if not f.endswith((".db", "-wal", "-shm", ".lock"))]


def test_dry_run_changes_nothing(conn, cfg):
    cid = add_card(conn, cfg)
    seen(conn, cid, 120)
    old = add_card(conn, cfg, created_days_ago=60)
    (cfg.settings.data_dir / "runs" / "x").mkdir(parents=True)
    conn.execute(
        "INSERT INTO runs(id, status, started_at, finished_at) VALUES ('x', 'finished', ?, ?)",
        (iso(50), iso(40)),
    )
    conn.execute("INSERT INTO story_views(repo, sha, seen_at) VALUES ('a', '1', ?)", (iso(40),))
    conn.commit()
    bury(conn, cfg)
    before = snapshot(conn, cfg)

    dry = gc.collect(conn, cfg, NOW, dry_run=True)

    assert snapshot(conn, cfg) == before
    assert exists(conn, old)
    assert gc.last_result(cfg) is None
    real = gc.collect(conn, cfg, NOW)
    assert dry == real
    assert dry["seen"] == 1 and dry["unseen"] == 1


def test_weights_unchanged_by_gc(conn, cfg):
    cid = add_card(conn, cfg)
    seen(conn, cid, 20)
    conn.execute(
        "INSERT INTO weights(feature, value, alpha, beta, updated_at) VALUES ('f', 'v', 2, 3, ?)",
        (iso(1),),
    )
    conn.commit()
    before = [tuple(r) for r in conn.execute("SELECT * FROM weights ORDER BY 1, 2")]

    gc.collect(conn, cfg, NOW)

    assert [tuple(r) for r in conn.execute("SELECT * FROM weights ORDER BY 1, 2")] == before


def test_last_result_written_and_read(conn, cfg):
    assert gc.last_result(cfg) is None
    gc.collect(conn, cfg, NOW)
    last = gc.last_result(cfg)
    assert last["at"] == NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert last["counts"]["seen"] == 0


def test_vacuum_runs(conn, cfg):
    gc.collect(conn, cfg, NOW, vacuum=True)


def add_lead(conn, path, seen_days_ago, covered=0):
    conn.execute(
        "INSERT INTO leads(repo, story_type, kind, path, lead_key, text, strength, head_sha, "
        "first_seen_at, last_seen_at, times_covered) "
        "VALUES ('r', 'hot_spot', 'path', ?, 'p:' || ?, 't', 1.0, 'h', ?, ?, ?)",
        (path, path, iso(400), iso(seen_days_ago), covered),
    )
    conn.commit()


def test_stale_uncovered_leads_are_deleted(conn, cfg):
    add_lead(conn, "old_uncovered", 200)
    add_lead(conn, "old_covered", 200, covered=1)
    add_lead(conn, "fresh_uncovered", 10)
    cid = add_card(conn, cfg)
    seen(conn, cid, 20)  # card gc never touches leads

    res = gc.collect(conn, cfg, NOW, dry_run=True)
    assert res["leads"] == 1
    assert count(conn, "SELECT COUNT(*) FROM leads") == 3

    res = gc.collect(conn, cfg, NOW)
    assert res["leads"] == 1
    left = {r[0] for r in conn.execute("SELECT path FROM leads")}
    assert left == {"old_covered", "fresh_uncovered"}


def test_big_logs_keep_their_newest_half(conn, cfg):
    logs = cfg.settings.data_dir / "logs"
    logs.mkdir(parents=True)
    big = logs / "api.log"
    big.write_text("".join(f"line {i}\n" for i in range(100_000)))  # ~1.1 MB
    small = logs / "rejected-events.log"
    small.write_text("one\n")
    gc.collect(conn, cfg, NOW, dry_run=True)
    assert big.stat().st_size > 1_000_000  # dry run leaves it
    counts = gc.collect(conn, cfg, NOW)
    text = big.read_text()
    assert counts["log_files"] == 1
    assert len(text) <= cfg.settings.gc.log_max_kb * 1024 // 2 + 20
    assert text.endswith("line 99999\n") and text.startswith("line ")  # whole lines only
    assert small.read_text() == "one\n"
