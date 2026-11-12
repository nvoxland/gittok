"""Knowledge per symbol."""

import json
import random
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from blamescroll import db, knowledge, learning, ledger, store
from tests.cards import text_card
from tests.conftest import make_config
from tests.test_candidate_leads import cand
from tests.test_ledger import NOW as LNOW
from tests.test_ledger import refresh

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
T = int(NOW.timestamp() * 1000)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    c.execute("INSERT INTO repos(name, path, ref) VALUES ('fixture', '/x', 'main')")
    c.execute("INSERT INTO repos(name, path, ref) VALUES ('r', '/y', 'main')")
    yield c
    c.close()


def rid(conn, name):
    return conn.execute("SELECT id FROM repos WHERE name = ?", (name,)).fetchone()[0]


def define(conn, repo, path, name, start, end, kind="function"):
    sym = f"{path}::{name}"
    conn.execute(
        'INSERT INTO fact_defines(fact_id, repo_id, path, symbol, name, kind, start, "end", '
        "size, params, depth, branches, public) VALUES (?,?,?,?,?,?,?,?,?,0,0,0,1)",
        (f"def-{repo}-{sym}", rid(conn, repo), path, sym, name, kind, start, end, end - start + 1),
    )
    conn.commit()
    return sym, f"def-{repo}-{sym}"


def call(conn, repo, caller, callee, path="x.py", line=1):
    conn.execute(
        "INSERT INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path, line, "
        "resolved, callee_symbol) VALUES (?,?,?,?,?,?,1,?)",
        (
            f"call-{caller}-{callee}",
            rid(conn, repo),
            caller,
            callee.split("::")[-1],
            path,
            line,
            callee,
        ),
    )
    conn.commit()


def add_card(conn, cfg, resolved=None, **over) -> str:
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), **over)
    acc = SimpleNamespace(card=spec, resolved=resolved or {}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now="2026-05-31T00:00:00Z")
    conn.commit()
    return cid


def see(conn, card, ts=T):
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', 'x')",
        (card, ts),
    )
    conn.commit()


def run(conn, cfg):
    return learning.process_events(conn, cfg, now=NOW)


def test_card_with_fact_ids_lowers_novelty_of_its_symbol_only(conn, cfg):
    f, fid = define(conn, "fixture", "src/a.py", "f", 1, 5)
    define(conn, "fixture", "src/a.py", "g", 10, 15)
    card = add_card(conn, cfg, resolved={"facts": [fid]})
    see(conn, card)
    run(conn, cfg)
    assert knowledge.symbol_novelty(conn, "fixture", f) < 1.0
    assert knowledge.symbol_novelty(conn, "fixture", "src/a.py::g") == 1.0


def test_symbols_derived_from_cited_ranges_and_backticks(conn, cfg):
    f, _ = define(conn, "fixture", "src/a.py", "f", 1, 5)
    define(conn, "fixture", "src/a.py", "g", 10, 15)
    h, _ = define(conn, "fixture", "src/b.py", "helper", 1, 3)
    visual = {
        "kind": "code", "repo": "fixture", "path": "src/a.py", "commit": "a" * 40, "lines": [2, 4],
    }  # fmt: skip
    card = add_card(conn, cfg, visual=visual, hook="Why does `helper()` exist?")
    assert sorted(knowledge.card_symbols(conn, card)) == [("fixture", f), ("fixture", h)]


def test_reprocessing_events_is_idempotent(conn, cfg):
    f, fid = define(conn, "fixture", "src/a.py", "f", 1, 5)
    card = add_card(conn, cfg, resolved={"facts": [fid]})
    see(conn, card)
    see(conn, card, ts=T + 1)
    run(conn, cfg)
    row = dict(conn.execute("SELECT * FROM knowledge_symbols").fetchone())
    assert row["seen"] == 1
    run(conn, cfg)
    assert dict(conn.execute("SELECT * FROM knowledge_symbols").fetchone()) == row


def test_answers_count_per_symbol(conn, cfg):
    f, fid = define(conn, "fixture", "src/a.py", "f", 1, 5)
    card = add_card(conn, cfg, resolved={"facts": [fid]})
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, 'answer', ?, ?, 'x')",
        (card, T, json.dumps({"correct": False})),
    )
    conn.commit()
    run(conn, cfg)
    row = conn.execute("SELECT * FROM knowledge_symbols").fetchone()
    assert (row["quiz_wrong"], row["seen"]) == (1, 0)
    assert knowledge.symbol_novelty(conn, "fixture", f) > 0.3


def seen_symbol(conn, repo, sym):
    conn.execute(
        "INSERT INTO knowledge_symbols(repo, symbol, seen, last_seen) VALUES (?, ?, 3, 1)",
        (repo, sym),
    )
    conn.commit()


def test_lead_next_door_to_a_seen_symbol_outranks_an_unrelated_one(conn, cfg):
    cand(conn, "lib/unrelated.py", 20, "core", rating=(4, "core"))
    cand(conn, "lib/next.py", 20, "core", rating=(4, "core"))
    s, _ = define(conn, "r", "lib/seen.py", "s", 1, 9)
    c, _ = define(conn, "r", "lib/next.py", "c", 20, 29)
    define(conn, "r", "lib/unrelated.py", "u", 20, 29)
    call(conn, "r", s, c)
    seen_symbol(conn, "r", s)
    refresh(conn, {})
    got = [x.path for x in ledger.ranked(conn, cfg, "r", "what_it_does", LNOW, 10)]
    assert got == ["lib/next.py", "lib/unrelated.py"]


def test_fully_seen_symbol_lead_is_damped(conn, cfg):
    cand(conn, "lib/a.py", 20, "core", rating=(4, "core"))
    cand(conn, "lib/b.py", 20, "core", rating=(4, "core"))
    a, _ = define(conn, "r", "lib/a.py", "a", 20, 29)
    define(conn, "r", "lib/b.py", "b", 20, 29)
    seen_symbol(conn, "r", a)
    refresh(conn, {})
    got = [x.path for x in ledger.ranked(conn, cfg, "r", "what_it_does", LNOW, 10)]
    assert got == ["lib/b.py", "lib/a.py"]


def test_map_files_report_symbol_coverage(conn, cfg):
    f, _ = define(conn, "fixture", "src/a.py", "f", 1, 5)
    define(conn, "fixture", "src/a.py", "g", 10, 15)
    define(conn, "fixture", "src/a.py", "K", 20, 30, kind="constant")
    seen_symbol(conn, "fixture", f)
    files = knowledge.map_files(conn, cfg, "fixture")
    assert files == [{"path": "src/a.py", "symbols_defined": 2, "symbols_seen": 1}]
