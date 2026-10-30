import json
from datetime import UTC, datetime, timedelta

import pytest

from codescroll import db, runs
from codescroll.config import (
    AgentSettings,
    AnalysisSettings,
    Config,
    Repo,
    ResearchSettings,
    ServerSettings,
    Settings,
)
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]
NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    repo = Repo(name="fixture", path=fixture_repo.path, ref="main")
    settings = Settings(
        data_dir=tmp_path / "data",
        server=ServerSettings(),
        agent=AgentSettings(max_count=20, per_day_runs=4),
        analysis=AnalysisSettings(),
        research=ResearchSettings(),
    )
    personas = {p: None for p in PERSONAS}
    return Config(
        root=tmp_path,
        repos={"fixture": repo},
        groups={},
        settings=settings,
        defaults={},
        personas=personas,
    )


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def test_submit_twice_accumulates_counts(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=5, now=NOW)
    bad = example_card(fixture_repo, dirs=["nope"])

    first = runs.submit(conn, cfg, run_id, {"cards": [example_card(fixture_repo), bad]})
    assert first["submission"] == 1
    assert [a["index"] for a in first["accepted"]] == [0]
    assert first["accepted"][0]["card_id"].startswith("c_")
    assert [r["reason"] for r in first["rejected"]] == ["unknown_dir"]
    assert first["totals"] == {"accepted": 1, "rejected": 1, "requested": 5, "remaining": 4}

    second = runs.submit(conn, cfg, run_id, [text_card(fixture_repo)])
    assert second["submission"] == 2
    assert second["totals"] == {"accepted": 2, "rejected": 1, "requested": 5, "remaining": 3}

    run = runs.get_run(conn, run_id)
    assert (run["accepted"], run["rejected"], run["submissions"]) == (2, 1, 2)
    assert run["status"] == "open"
    assert run["reject_reasons"] == [
        {
            "index": 1,
            "reason": "unknown_dir",
            "detail": run["reject_reasons"][0]["detail"],
            "submission": 1,
        }
    ]
    assert conn.execute("SELECT COUNT(*) FROM cards WHERE run_id = ?", (run_id,)).fetchone()[0] == 2


@pytest.mark.parametrize("requested", [0, -1, 21])
def test_open_run_rejects_requested_out_of_bounds(conn, cfg, requested):
    with pytest.raises(runs.RunError, match="requested"):
        runs.open_run(conn, cfg, repo=None, brief="b", requested=requested, now=NOW)
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_daily_run_limit(conn, cfg):
    ids = [
        runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW + timedelta(hours=i))
        for i in range(4)
    ]
    later = NOW + timedelta(hours=5)
    with pytest.raises(
        runs.RunLimitError,
        match=r"daily run limit reached \(4\); try again after "
        r"2026-03-02T12:00:00Z",
    ):
        runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=later)
    assert issubclass(runs.RunLimitError, runs.RunError)

    # once the oldest run is more than 24h old, a slot frees up
    runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW + timedelta(hours=25))
    assert len(set(ids)) == 4


def test_finish_run_summary_and_idempotence(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=3, now=NOW)
    bads = [example_card(fixture_repo, dirs=["nope"]) for _ in range(2)]
    runs.submit(conn, cfg, run_id, [example_card(fixture_repo), *bads, {"x": 1}])

    done = NOW + timedelta(seconds=90)
    summary = runs.finish_run(conn, run_id, notes={"mood": "ok"}, now=done)
    assert summary == {
        "run_id": run_id,
        "status": "finished",
        "accepted": 1,
        "rejected": 3,
        "submissions": 1,
        "duration_ms": 90_000,
        "top_reject_reasons": [["unknown_dir", 2], ["schema", 1]],
        "mcp_calls": {},
    }
    run = runs.get_run(conn, run_id)
    assert run["finished_at"] == "2026-03-01T12:01:30Z"
    assert run["meta"]["notes"] == {"mood": "ok"}

    again = runs.finish_run(conn, run_id, notes={"mood": "changed"}, now=done + timedelta(hours=1))
    assert again == summary
    assert runs.get_run(conn, run_id)["meta"]["notes"] == {"mood": "ok"}


def test_submit_to_finished_run_is_an_error(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    runs.finish_run(conn, run_id, now=NOW)
    with pytest.raises(runs.RunError, match=f"run {run_id} is finished; call get_brief"):
        runs.submit(conn, cfg, run_id, [example_card(fixture_repo)])
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0


def test_submit_to_unknown_run_is_an_error(conn, cfg, fixture_repo):
    with pytest.raises(runs.RunError, match="r_nope"):
        runs.submit(conn, cfg, "r_nope", [example_card(fixture_repo)])


@pytest.mark.parametrize("bad", ["text", None, 3, {"cards": "nope"}, {"other": []}, {}])
def test_submit_rejects_bad_shape(conn, cfg, bad):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    with pytest.raises(runs.RunError, match="cards"):
        runs.submit(conn, cfg, run_id, bad)
    assert runs.get_run(conn, run_id)["submissions"] == 0


def test_duplicate_story_across_runs_is_rejected(conn, cfg, fixture_repo):
    first = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    runs.submit(conn, cfg, first, [example_card(fixture_repo)])
    runs.finish_run(conn, first, now=NOW)

    second = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    res = runs.submit(conn, cfg, second, [example_card(fixture_repo), text_card(fixture_repo)])
    assert res["rejected"] == [
        {"index": 0, "reason": "duplicate_story", "detail": "already in the feed"}
    ]
    assert [a["index"] for a in res["accepted"]] == [1]
    assert res["totals"]["accepted"] == 1
    assert res["totals"]["rejected"] == 1
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2


def test_raw_submission_saved_to_disk(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    payload = {"cards": [example_card(fixture_repo), {"junk": True}]}
    runs.submit(conn, cfg, run_id, payload)
    runs.submit(conn, cfg, run_id, [text_card(fixture_repo)])

    d = cfg.settings.data_dir / "runs" / run_id
    assert json.loads((d / "submission-1.json").read_text()) == payload
    assert json.loads((d / "submission-2.json").read_text()) == [text_card(fixture_repo)]


def test_expire_stale_only_touches_old_open_runs(conn, cfg):
    old = runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW)
    old_done = runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW)
    runs.finish_run(conn, old_done, now=NOW)
    young = runs.open_run(
        conn, cfg, repo=None, brief="b", requested=1, now=NOW + timedelta(hours=20)
    )

    assert runs.expire_stale(conn, hours=24, now=NOW + timedelta(hours=25)) == 1
    assert runs.get_run(conn, old)["status"] == "expired"
    assert runs.get_run(conn, old_done)["status"] == "finished"
    assert runs.get_run(conn, young)["status"] == "open"
    assert runs.expire_stale(conn, hours=24, now=NOW + timedelta(hours=25)) == 0


def test_open_run_expires_stale_runs_first(conn, cfg):
    old = runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW)
    runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW + timedelta(hours=30))
    assert runs.get_run(conn, old)["status"] == "expired"


def test_bump_call_counts_per_tool(conn, cfg):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW)
    runs.bump_call(conn, run_id, "get_brief")
    runs.bump_call(conn, run_id, "submit_cards")
    runs.bump_call(conn, run_id, "submit_cards")
    runs.bump_call(conn, "r_missing", "submit_cards")  # no-op
    assert runs.get_run(conn, run_id)["meta"]["mcp_calls"] == {"get_brief": 1, "submit_cards": 2}
    assert runs.finish_run(conn, run_id, now=NOW)["mcp_calls"] == {
        "get_brief": 1,
        "submit_cards": 2,
    }
