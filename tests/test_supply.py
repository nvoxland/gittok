from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from gittok import db, learning, supply
from tests.cards import meme_card
from tests.conftest import make_config
from tests.test_slotter import add_card, impress

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    yield c
    c.close()


def fill(conn, cfg, n):
    return [add_card(conn, cfg) for _ in range(n)]


def burn_cards(conn, cfg, n, days=7):
    """n distinct cards impressed per day, over `days` days."""
    for d in range(days):
        for cid in fill(conn, cfg, n):
            impress(conn, cid, NOW - timedelta(days=d, hours=1))


def test_want_is_zero_when_runway_meets_target(conn, cfg):
    fill(conn, cfg, 30)  # 3 days * floor 10 = 30
    h = supply.feed_health(conn, cfg, NOW)
    assert h["backlog"] == 30 and h["want"] == 0
    assert h["runway_days"] == 3.0 and h["target_days"] == 3


def test_burn_uses_min_floor(conn, cfg):
    assert supply.burn_per_day(conn, NOW) == 0
    assert supply.feed_health(conn, cfg, NOW)["burn_per_day"] == 10  # floor
    burn_cards(conn, cfg, 20)  # measured 20 per day beats the floor
    assert supply.burn_per_day(conn, NOW) == 20
    assert supply.feed_health(conn, cfg, NOW)["burn_per_day"] == 20


def test_want_clamps_to_max_count(conn, cfg):
    h = supply.feed_health(conn, cfg, NOW)  # empty: ceil(3 * 10) = 30, max_count is 20
    assert h["want"] == cfg.settings.agent.max_count == 20
    fill(conn, cfg, 18)
    assert supply.feed_health(conn, cfg, NOW)["want"] == 12


def test_small_shortfall_still_makes_a_full_run(conn, cfg):
    """A run has a fixed start-up cost, so a short feed gets min_run_count cards, not 1 or 2."""
    fill(conn, cfg, 28)  # 2 short of 30
    assert supply.feed_health(conn, cfg, NOW)["want"] == cfg.settings.agent.min_run_count == 8


def test_unseen_ready_excludes_recent_impressions(conn, cfg):
    seen, old, fresh = fill(conn, cfg, 3)
    impress(conn, seen, NOW - timedelta(days=1))
    impress(conn, old, NOW - timedelta(days=30))
    rc = learning.load_reward_config(cfg)
    assert supply.unseen_ready(conn, rc, NOW) == sorted([old, fresh])


def test_image_share_and_pending(conn, cfg):
    visual = meme_card(SimpleNamespace(shas={"delete_legacy": "abc"}))["visual"]
    add_card(conn, cfg)
    img = add_card(conn, cfg, visual=visual)
    conn.execute("UPDATE cards SET status = 'ready'")
    conn.commit()
    h = supply.feed_health(conn, cfg, NOW)
    assert h["image_share"] == {"ready": 0.5, "shown_7d": 0.0}
    impress(conn, img, NOW - timedelta(hours=1))
    assert supply.feed_health(conn, cfg, NOW)["image_share"]["shown_7d"] == 1.0
    assert h["pending_render"] == 0 and h["db_mb"] == 0 and h["assets_mb"] == 0


def test_low_runway_notification_once_per_day(conn, cfg):
    assert supply.notify_low_runway(conn, cfg, NOW) == 1  # empty backlog: runway 0
    assert supply.notify_low_runway(conn, cfg, NOW + timedelta(hours=3)) == 0
    assert supply.notify_low_runway(conn, cfg, NOW + timedelta(days=1)) == 1
    rows = conn.execute("SELECT kind, dedup_key FROM notifications ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("low_runway", "low_runway:2026-06-01"),
        ("low_runway", "low_runway:2026-06-02"),
    ]
    fill(conn, cfg, 30)
    assert supply.notify_low_runway(conn, cfg, NOW + timedelta(days=2)) == 0


def test_feed_health_reports_last_gc_pass(conn, cfg):
    from gittok import gc

    assert supply.feed_health(conn, cfg, NOW)["gc"] is None
    cfg.settings.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.settings.data_dir / gc.LAST_FILE).write_text('{"at": "x", "counts": {"seen": 3}}')
    assert supply.feed_health(conn, cfg, NOW)["gc"] == {"at": "x", "counts": {"seen": 3}}


def test_wants_cards_signal_appends_a_fixed_line_with_cooldown(conn, cfg):
    log = cfg.settings.data_dir / supply.WANTS_FILE
    assert supply.signal_wants_cards(conn, cfg, NOW) == 1  # empty backlog wants cards
    assert log.read_text() == f'{{"at":"{NOW.isoformat()}","want":20}}\n'  # one JSON object
    assert supply.parse_wants(log.read_text()) == [{"at": NOW, "want": 20}]
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(hours=1)) == 0  # cooldown
    later = NOW + timedelta(hours=cfg.settings.agent.wake_cooldown_hours, minutes=1)
    assert supply.signal_wants_cards(conn, cfg, later) == 1
    assert len(log.read_text().splitlines()) == 2


def test_wants_cards_signal_is_silent_while_a_run_is_open_or_feed_is_full(conn, cfg):
    from gittok import runs

    log = cfg.settings.data_dir / supply.WANTS_FILE
    runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=NOW)
    assert supply.signal_wants_cards(conn, cfg, NOW) == 0
    conn.execute("UPDATE runs SET status = 'finished'")
    conn.commit()
    fill(conn, cfg, 30)
    assert supply.signal_wants_cards(conn, cfg, NOW) == 0
    assert not log.exists()


def test_wants_cards_signal_is_silent_with_no_repos(conn, cfg):
    """Nothing can be generated yet, so the watch must not wake a session."""
    from dataclasses import replace

    empty = replace(cfg, repos={})
    assert supply.signal_wants_cards(conn, empty, NOW) == 0
    assert not (cfg.settings.data_dir / supply.WANTS_FILE).exists()


def test_parse_wants_keeps_only_complete_valid_lines():
    good = supply.wants_line(NOW, 7)
    assert good.endswith("\n") and "\n" not in good[:-1]
    text = (
        "2026-01-01T00:00:00+00:00 want 20 cards\n"  # not JSON
        "[1, 2]\n"
        '{"at": "not a time", "want": 3}\n'
        '{"at": "2026-01-01T00:00:00+00:00", "want": "many"}\n'
        '{"at": "2026-01-01T00:00:00+00:00", "want": true}\n'
        '{"at": "2026-01-01T00:00:00", "want": 3}\n'  # no time zone
        "\n" + good + good[: len(good) // 2]  # the last line is still being written
    )
    assert supply.parse_wants(text) == [{"at": NOW, "want": 7}]
    assert supply.parse_wants("") == []
    assert supply.parse_wants(good[:-1]) == []  # no newline yet: not a whole line


def _finish_runs(conn):
    conn.execute("UPDATE runs SET status = 'finished'")
    conn.commit()


def test_an_empty_feed_signals_inside_the_cooldown_once_a_run_answered_the_last_line(conn, cfg):
    """The reader reached the end of the feed: do not wait for the cooldown."""
    from gittok import runs

    log = cfg.settings.data_dir / supply.WANTS_FILE
    assert supply.signal_wants_cards(conn, cfg, NOW) == 1
    # No run answered that line: a second line would say nothing new.
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=30)) == 0
    runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=NOW + timedelta(minutes=5))
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=30)) == 0  # run open
    _finish_runs(conn)
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=30)) == 1
    assert supply.signal_wants_cards(conn, cfg, NOW + timedelta(minutes=31)) == 0
    assert len(log.read_text().splitlines()) == 2


def test_a_low_feed_that_is_not_empty_still_waits_for_the_cooldown(conn, cfg):
    from gittok import runs

    assert supply.signal_wants_cards(conn, cfg, NOW) == 1
    runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=NOW + timedelta(minutes=5))
    _finish_runs(conn)
    fill(conn, cfg, 1)
    later = NOW + timedelta(minutes=30)
    assert supply.feed_health(conn, cfg, later)["want"] > 0
    assert supply.signal_wants_cards(conn, cfg, later) == 0


def test_wants_cards_signal_is_silent_at_the_daily_run_cap(conn, cfg):
    from gittok import runs

    for i in range(cfg.settings.agent.per_day_runs):
        at = NOW - timedelta(hours=i + 5)
        runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=at)
    _finish_runs(conn)
    assert runs.cap_reached(conn, cfg, NOW)
    assert supply.signal_wants_cards(conn, cfg, NOW) == 0
    assert not (cfg.settings.data_dir / supply.WANTS_FILE).exists()
    assert not runs.cap_reached(conn, cfg, NOW + timedelta(hours=24))


def test_run_open_is_true_only_for_a_fresh_open_run(conn, cfg):
    from gittok import runs

    assert not supply.run_open(conn, cfg, NOW)
    runs.open_run(conn, cfg, repo=None, brief="b", requested=5, now=NOW)
    assert supply.run_open(conn, cfg, NOW + timedelta(minutes=1))
    stale = NOW + timedelta(hours=cfg.settings.agent.wake_cooldown_hours, minutes=1)
    assert not supply.run_open(conn, cfg, stale)  # an abandoned run does not count
    _finish_runs(conn)
    assert not supply.run_open(conn, cfg, NOW + timedelta(minutes=1))
