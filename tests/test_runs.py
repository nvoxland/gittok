import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from blamescroll import db, runs
from blamescroll.config import (
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
        "seconds_per_card": 90.0,
        "top_reject_reasons": [["unknown_dir", 2], ["schema", 1]],
        "mcp_calls": {},
        "packets": {},
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
    assert [(r["index"], r["reason"]) for r in res["rejected"]] == [(0, "duplicate_story")]
    assert "already told in format code_card" in res["rejected"][0]["detail"]
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


def _variants(fixture_repo, n):
    """n cards with different story_keys (story_type is part of the key)."""
    # Each story type here allows the text format it is paired with (brief.STORY_FORMATS).
    types = [
        ("rip", "text_post"),
        ("whose_code", "text_post"),
        ("what_it_does", "eli5"),
        ("analogy", "eli5"),
        ("snippet_callouts", "eli5"),
    ]
    return [text_card(fixture_repo, story_type=t, format=f) for t, f in types[:n]]


def _threaded_submit(cfg, run_id, payloads):
    import threading

    path = cfg.settings.data_dir / "blamescroll.db"
    barrier = threading.Barrier(len(payloads))
    results, errors = [], []

    def work(payload):
        c = db.open_db(path)
        try:
            barrier.wait()
            results.append(runs.submit(c, cfg, run_id, payload))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            c.close()

    ts = [threading.Thread(target=work, args=(p,)) for p in payloads]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return results, errors


def test_parallel_submits_keep_counters_and_files(cfg, fixture_repo):
    c = db.open_db(cfg.settings.data_dir / "blamescroll.db")
    run_id = runs.open_run(c, cfg, repo=None, brief="b", requested=10, now=NOW)
    cards = _variants(fixture_repo, 4)
    results, errors = _threaded_submit(cfg, run_id, [[x] for x in cards])
    assert errors == []
    assert sorted(r["submission"] for r in results) == [1, 2, 3, 4]
    run = runs.get_run(c, run_id)
    assert (run["accepted"], run["submissions"]) == (4, 4)
    files = sorted(p.name for p in (cfg.settings.data_dir / "runs" / run_id).iterdir())
    assert files == [f"submission-{i}.json" for i in range(1, 5)]


def test_submit_accepts_variant_of_a_good_old_story_in_a_new_format(conn, cfg, fixture_repo):
    first = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    runs.submit(conn, cfg, first, [text_card(fixture_repo)])
    runs.finish_run(conn, first, now=NOW)
    variant = text_card(fixture_repo, format="fun_fact", hook="Legacy.py, retold.")

    # The variant lead in the packet names the format, so the validator allows it for `rip`.
    ref = {"kind": "variant", "story_type": "rip", "format": "fun_fact", "story_key": "k"}
    packets = [{"id": "p1", "repo": "fixture", "count": 1, "lead_refs": [ref]}]
    second = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, packets=packets, now=NOW)
    res = runs.submit(conn, cfg, second, [variant])  # too soon, no reward yet
    assert "reward" in res["rejected"][0]["detail"]
    conn.execute("UPDATE stories SET best_reward = 0.9")
    res = runs.submit(conn, cfg, second, [variant])
    assert "days old" in res["rejected"][0]["detail"]
    conn.execute("UPDATE stories SET last_card_at = '2020-01-01T00:00:00Z'")
    assert runs.check(conn, cfg, second, [variant])["ok"] == [0]
    res = runs.submit(conn, cfg, second, [variant])
    assert [a["index"] for a in res["accepted"]] == [0]
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
    story = conn.execute("SELECT * FROM stories").fetchone()
    assert (story["cards_made"], db.loads(story["formats"])) == (2, ["text_post", "fun_fact"])
    again = runs.submit(conn, cfg, second, [variant])  # same format twice is never allowed
    assert "already told" in again["rejected"][0]["detail"]


def test_parallel_duplicate_story_stored_once(cfg, fixture_repo):
    c = db.open_db(cfg.settings.data_dir / "blamescroll.db")
    run_id = runs.open_run(c, cfg, repo=None, brief="b", requested=10, now=NOW)
    same = [text_card(fixture_repo)]
    results, errors = _threaded_submit(cfg, run_id, [same, same, same])
    assert errors == []
    assert c.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    assert runs.get_run(c, run_id)["accepted"] == 1
    assert sum(len(r["accepted"]) for r in results) == 1


def test_story_key_unique_index_exists(conn):
    conn.execute("INSERT INTO repos(name, path) VALUES ('r', 'p')")
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('r1', 'open', 't')")
    sql = (
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec, "
        "status, story_key, created_at) VALUES (?, 'r1', 1, 'a', 'b', 'c', 'd', '{}', "
        "'ready', 'same', 't')"
    )
    conn.execute(sql, ("c1",))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(sql, ("c2",))


def test_submit_rejects_more_than_40_cards_per_call(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=20, now=NOW)
    with pytest.raises(runs.RunError, match="40"):
        runs.submit(conn, cfg, run_id, [{"junk": i} for i in range(41)])
    assert runs.get_run(conn, run_id)["submissions"] == 0


def test_submit_over_quota_cards_rejected_keeping_first(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=2, now=NOW)
    cards = _variants(fixture_repo, 4)
    res = runs.submit(conn, cfg, run_id, cards)
    assert [a["index"] for a in res["accepted"]] == [0, 1]
    assert [(r["index"], r["reason"]) for r in res["rejected"]] == [
        (2, "over_quota"),
        (3, "over_quota"),
    ]
    assert res["totals"] == {"accepted": 2, "rejected": 2, "requested": 2, "remaining": 0}
    again = runs.submit(
        conn, cfg, run_id, [text_card(fixture_repo, story_type="snippet_callouts", format="eli5")]
    )
    assert [r["reason"] for r in again["rejected"]] == ["over_quota"]
    assert runs.get_run(conn, run_id)["accepted"] == 2


def test_bump_call_ignores_non_open_runs(conn, cfg):
    run_id = runs.open_run(conn, cfg, repo=None, brief="b", requested=1, now=NOW)
    runs.finish_run(conn, run_id, now=NOW)
    runs.bump_call(conn, run_id, "git_log")
    assert runs.get_run(conn, run_id)["meta"]["mcp_calls"] == {}


def test_bump_call_is_atomic_across_connections(cfg):
    import threading

    path = cfg.settings.data_dir / "blamescroll.db"
    c = db.open_db(path)
    run_id = runs.open_run(c, cfg, repo=None, brief="b", requested=1, now=NOW)
    barrier = threading.Barrier(6)

    def work():
        cc = db.open_db(path)
        barrier.wait()
        for _ in range(10):
            runs.bump_call(cc, run_id, "git_log")
        cc.close()

    ts = [threading.Thread(target=work) for _ in range(6)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert runs.get_run(c, run_id)["meta"]["mcp_calls"] == {"git_log": 60}


def _m2_cfg(cfg, budget=4):
    import dataclasses

    from blamescroll.config import Mascot, MemeTemplate, RenderSettings

    return dataclasses.replace(
        cfg,
        settings=dataclasses.replace(
            cfg.settings, render=RenderSettings(max_illustrations_per_run=budget)
        ),
        mascots={"otter": Mascot("otter", "fixture", "s", 1)},
        meme_templates={"drake": MemeTemplate("drake", 2)},
    )


def test_submit_tracks_illustration_budget_per_run(conn, cfg, fixture_repo):
    from tests import cards as C

    cfg = _m2_cfg(cfg, budget=3)
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=5, now=NOW)
    comic = C.comic_card(fixture_repo, panels=2)
    comic["sources"] = [{"repo": "fixture", "path": "README.md"}]
    first = runs.submit(conn, cfg, run_id, [comic])
    assert [a["index"] for a in first["accepted"]] == [0]
    assert runs.get_run(conn, run_id)["meta"]["illustrations"] == 2
    assert conn.execute("SELECT status FROM cards").fetchone()[0] == "pending_render"

    comic2 = C.comic_card(fixture_repo, panels=2)  # needs 2, only 1 left
    second = runs.submit(conn, cfg, run_id, [comic2])
    assert [r["reason"] for r in second["rejected"]] == ["illustration_budget"]
    assert runs.get_run(conn, run_id)["meta"]["illustrations"] == 2

    one = C.illustration_card(fixture_repo)
    third = runs.submit(conn, cfg, run_id, [one])
    assert third["rejected"] == []
    assert runs.get_run(conn, run_id)["meta"]["illustrations"] == 3


def test_submit_uses_config_templates_and_signals(conn, cfg, fixture_repo):
    from blamescroll import signals
    from tests import cards as C

    cfg = _m2_cfg(cfg)
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=5, now=NOW)
    res = runs.submit(conn, cfg, run_id, [C.meme_card(fixture_repo), C.chart_card(fixture_repo)])
    assert [a["index"] for a in res["accepted"]] == [0]
    assert [r["reason"] for r in res["rejected"]] == ["chart_no_data"]
    assert signals.load_signals(conn, "fixture") is None


PACKETS = [
    {"id": "p1", "repo": "fixture", "count": 2, "formats": ["text_post", "code_card"]},
    {"id": "p2", "repo": "fixture", "count": 1, "formats": ["text_post"]},
]


def test_open_run_stores_packets_and_get_packet_returns_one(conn, cfg):
    run_id = runs.open_run(
        conn, cfg, repo="fixture", brief="b", requested=3, packets=PACKETS, now=NOW
    )
    assert runs.get_packet(conn, run_id, "p2") == PACKETS[1]
    with pytest.raises(runs.RunError, match="unknown packet p9"):
        runs.get_packet(conn, run_id, "p9")
    with pytest.raises(runs.RunError, match="unknown run"):
        runs.get_packet(conn, "r_nope", "p1")


def test_submit_with_packet_id_counts_per_packet(conn, cfg, fixture_repo):
    run_id = runs.open_run(
        conn, cfg, repo="fixture", brief="b", requested=3, packets=PACKETS, now=NOW
    )
    bad = example_card(fixture_repo, dirs=["nope"])
    runs.submit(conn, cfg, run_id, [example_card(fixture_repo), bad], packet_id="p1")
    runs.submit(conn, cfg, run_id, [text_card(fixture_repo)], packet_id="p1")
    meta = runs.get_run(conn, run_id)["meta"]
    assert meta["packet_results"] == {"p1": {"accepted": 2, "rejected": 1, "submissions": 2}}
    with pytest.raises(runs.RunError, match="unknown packet p9"):
        runs.submit(conn, cfg, run_id, [text_card(fixture_repo)], packet_id="p9")


def test_check_reports_rejects_and_stores_nothing(conn, cfg, fixture_repo):
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=3, now=NOW)
    bad = example_card(fixture_repo, dirs=["nope"])
    good = example_card(fixture_repo)
    out = runs.check(conn, cfg, run_id, [good, bad])
    assert out["ok"] == [0]
    assert [(r["index"], r["reason"]) for r in out["rejected"]] == [(1, "unknown_dir")]
    run = runs.get_run(conn, run_id)
    assert (run["accepted"], run["rejected"], run["submissions"]) == (0, 0, 0)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
    # A card already in the feed is flagged as a duplicate by check too.
    runs.submit(conn, cfg, run_id, [good])
    again = runs.check(conn, cfg, run_id, [good])
    assert [r["reason"] for r in again["rejected"]] == ["duplicate_story"]


def test_seconds_per_card_rounds_and_is_none_without_cards(conn, cfg, fixture_repo):
    a = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    runs.submit(conn, cfg, a, [example_card(fixture_repo), text_card(fixture_repo)])
    done = runs.finish_run(conn, a, now=NOW + timedelta(seconds=25))
    assert done["accepted"] == 2 and done["seconds_per_card"] == 12.5
    b = runs.open_run(conn, cfg, repo=None, brief="b", requested=3, now=NOW)
    assert runs.finish_run(conn, b, now=NOW + timedelta(seconds=25))["seconds_per_card"] is None


def _lead_row(conn, **kw) -> int:
    row = {"kind": "path", "path": "", "commit_sha": "", "blob_sha": ""} | kw
    cur = conn.execute(
        "INSERT INTO leads(repo, story_type, kind, path, commit_sha, blob_sha, lead_key, text, "
        "strength, head_sha, first_seen_at, last_seen_at) "
        "VALUES ('fixture', 'commit_drama', ?, ?, ?, ?, ?, 't', 1.0, 'h', 'x', 'x')",
        (
            row["kind"],
            row["path"],
            row["commit_sha"],
            row["blob_sha"],
            f"{row['kind']}:{row['path']}:{row['commit_sha']}",
        ),
    )
    return cur.lastrowid


def test_submit_marks_lead_covered(conn, cfg, fixture_repo):
    fix1 = fixture_repo.shas["fix1"]
    by_commit = _lead_row(conn, kind="commit", commit_sha=fix1, path="billing/invoice.py")
    other = _lead_row(conn, path="src/other.py")
    refs = [
        {"story_type": "what_it_does", "repo": "fixture", "kind": "path", "path": "src/other.py",
         "id": other},
        {"story_type": "what_it_does", "repo": "fixture", "kind": "commit", "commit": fix1,
         "path": "billing/invoice.py", "id": by_commit},
    ]  # fmt: skip
    packets = [{"id": "p1", "repo": "fixture", "count": 2, "lead_refs": refs}]
    run_id = runs.open_run(
        conn, cfg, repo="fixture", brief="b", requested=3, packets=packets, now=NOW
    )
    res = runs.submit(
        conn, cfg, run_id, [example_card(fixture_repo), text_card(fixture_repo)], packet_id="p1"
    )
    hit, miss = (a["card_id"] for a in res["accepted"])

    def lead_id(card_id):
        return conn.execute("SELECT lead_id FROM cards WHERE id = ?", (card_id,)).fetchone()[0]

    assert lead_id(hit) == by_commit
    assert lead_id(miss) is None
    row = conn.execute(
        "SELECT times_covered, last_covered_at FROM leads WHERE id = ?", (by_commit,)
    ).fetchone()
    assert row["times_covered"] == 1 and row["last_covered_at"] > "2026"
    assert conn.execute("SELECT times_covered FROM leads WHERE id = ?", (other,)).fetchone()[0] == 0


def test_submit_without_packet_marks_nothing(conn, cfg, fixture_repo):
    lead = _lead_row(conn, path="billing/invoice.py")
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=3, now=NOW)
    runs.submit(conn, cfg, run_id, [example_card(fixture_repo)])
    assert conn.execute("SELECT times_covered FROM leads WHERE id = ?", (lead,)).fetchone()[0] == 0


def test_rejected_card_penalizes_the_lead_it_cited(conn, cfg, fixture_repo):
    lead = _lead_row(conn, path="billing/invoice.py")
    refs = [
        {"story_type": "what_it_does", "repo": "fixture", "kind": "path",
         "path": "billing/invoice.py", "id": lead}
    ]  # fmt: skip
    packets = [{"id": "p1", "repo": "fixture", "count": 1, "lead_refs": refs}]
    run_id = runs.open_run(
        conn, cfg, repo="fixture", brief="b", requested=3, packets=packets, now=NOW
    )
    bad = example_card(fixture_repo, dirs=["nope"])
    res = runs.submit(conn, cfg, run_id, [bad], packet_id="p1")
    assert [r["reason"] for r in res["rejected"]] == ["unknown_dir"]
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead,)).fetchone()
    assert row["times_rejected"] == 1 and row["last_rejected_at"] > "2026"
    assert row["times_covered"] == 0
