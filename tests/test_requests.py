import json
import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gittok import api, db, knowledge, learning, ledger, runs, store
from tests.cards import explain, meme_card, text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
T = int(NOW.timestamp() * 1000)
SRC = [{"repo": "fixture", "path": "src/app.py", "lines": [1, 2]}]


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


def path_card(fixture_repo, **over):
    over = {"story_type": "what_it_does", "format": "eli5", "sources": SRC, "dirs": ["src"], **over}
    card = text_card(fixture_repo, **over)
    card["depth"][0]["text"] = explain("src/app.py")  # the explain floor needs a cited name
    return card


def add_card(conn, cfg, spec) -> str:
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def ev(conn, card, type_, ts=T):
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, '{}', 'x')",
        (card, type_, ts),
    )
    conn.commit()


def reqs(conn):
    return conn.execute("SELECT * FROM requests ORDER BY id").fetchall()


def req_leads(conn):
    return conn.execute("SELECT * FROM leads WHERE lead_key LIKE 'req:%' ORDER BY id").fetchall()


def test_teach_more_creates_one_request_even_if_sent_twice(conn, cfg, fixture_repo):
    cid = add_card(conn, cfg, meme_card(fixture_repo))
    ev(conn, cid, "teach_more")
    ev(conn, cid, "teach_more", ts=T + 5)
    learning.process_events(conn, cfg, now=NOW)
    learning.process_events(conn, cfg, now=NOW)
    (r,) = reqs(conn)
    assert (r["card_id"], r["repo"], r["path"], r["served_at"]) == (
        cid,
        "fixture",
        "src/app.py",
        None,
    )
    assert json.loads(r["dirs"]) == ["src"]
    assert len(req_leads(conn)) == 1


def test_request_becomes_a_strong_lead_by_path_or_commit(conn, cfg, fixture_repo):
    a = add_card(conn, cfg, meme_card(fixture_repo))
    b = add_card(conn, cfg, text_card(fixture_repo))
    ev(conn, a, "teach_more")
    ev(conn, b, "teach_more")
    learning.process_events(conn, cfg, now=NOW)
    la, lb = sorted(req_leads(conn), key=lambda r: r["story_type"] != "what_it_does")
    assert la["lead_key"].startswith("req:") and la["strength"] == 2.0
    assert (la["story_type"], la["kind"], la["path"]) == ("what_it_does", "path", "src/app.py")
    assert (lb["story_type"], lb["kind"]) == ("before_after", "commit")
    assert lb["commit_sha"] == fixture_repo.shas["delete_legacy"]
    assert "follow-up" in la["text"] and "A short hook." in la["text"]


def test_request_lead_ranks_first_and_survives_a_later_refresh(conn, cfg, fixture_repo):
    a = add_card(conn, cfg, meme_card(fixture_repo))
    ev(conn, a, "teach_more")
    learning.process_events(conn, cfg, now=NOW)
    later = datetime(2026, 6, 2, tzinfo=UTC)
    sig = {"churn": {"files": {"90": [{"path": "x/y.py", "commits": 9, "lines": 90}]}}}
    ledger.refresh(conn, "fixture", sig, 0, "h2", {"x/y.py": "a" * 40}, later)
    out = ledger.for_brief(conn, cfg, ["fixture"], later)
    first = out[("fixture", "what_it_does")][0]
    assert first.key.startswith("req:") and first.path == "src/app.py"


def test_covering_card_marks_served_and_lead_is_no_longer_offered(conn, cfg, fixture_repo):
    a = add_card(conn, cfg, meme_card(fixture_repo))
    ev(conn, a, "teach_more")
    learning.process_events(conn, cfg, now=NOW)
    (lead,) = req_leads(conn)
    ref = {"id": lead["id"], "story_type": "rip", "kind": "path", "path": "src/app.py"}
    assert ledger.match_lead(meme_card(fixture_repo), [ref]) == ref
    with db.immediate(conn):
        ledger.mark_covered(conn, lead["id"], NOW)
    (r,) = reqs(conn)
    assert r["served_at"] is not None
    out = ledger.for_brief(conn, cfg, ["fixture"], NOW)
    assert not any(x.key.startswith("req:") for x in out.get(("fixture", "rip"), []))
    learning.process_events(conn, cfg, now=NOW)  # does not resurrect it
    assert reqs(conn)[0]["served_at"] is not None and len(req_leads(conn)) == 1


def test_submit_with_request_lead_marks_served(conn, cfg, fixture_repo):
    a = add_card(conn, cfg, meme_card(fixture_repo))
    ev(conn, a, "teach_more")
    learning.process_events(conn, cfg, now=NOW)
    (lead,) = req_leads(conn)
    ref = {"id": lead["id"], "story_type": "what_it_does", "kind": "path", "path": "src/app.py"}
    packets = [{"id": "p1", "repo": "fixture", "count": 1, "lead_refs": [ref]}]
    run_id = runs.open_run(
        conn, cfg, repo="fixture", brief="b", requested=3, packets=packets, now=NOW
    )
    runs.submit(conn, cfg, run_id, [path_card(fixture_repo, hook="Deeper.")], packet_id="p1")
    assert reqs(conn)[0]["served_at"] is not None


def test_knew_it_event_through_api_lowers_novelty(cfg, fixture_repo):
    client = TestClient(api.create_app(lambda: cfg))
    with db.open_db(cfg.settings.data_dir / "gittok.db") as c:
        run_id = runs.open_run(c, cfg, repo=None, brief="b", requested=5)
        (acc,) = runs.submit(c, cfg, run_id, [path_card(fixture_repo)])["accepted"]
        cid = acc["card_id"]
        before = knowledge.novelty(c, "fixture", "src")
    body = {"events": [{"card_id": cid, "type": "knew_it", "ts": T, "data": {"on": True}}]}
    assert client.post("/api/events", json=body).json() == {"stored": 1}
    with db.open_db(cfg.settings.data_dir / "gittok.db") as c:
        learning.process_events(c, cfg, now=NOW)
        assert knowledge.novelty(c, "fixture", "src") < before
