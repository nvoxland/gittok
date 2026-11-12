"""Quizzes from facts: seeds in the brief, answer_fact in the validator."""

import copy

import pytest

from gittok import db, quizfacts, validator
from gittok.config import Repo
from tests import cards as C
from tests.test_brief import build
from tests.test_validator import PERSONAS as V_PERSONAS

SHA_A = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
SHA_B = "b2c3d4e5f60718293a4b5c6d7e8f9012345678aa"
SHA_C = "c3d4e5f60718293a4b5c6d7e8f9012345678aabb"
_n = [0]


def _id(prefix):
    _n[0] += 1
    return f"{prefix}-{_n[0]:012x}"


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(tmp_path / "t.db")
    c.execute("INSERT INTO repos(name, path, ref) VALUES ('fixture', '/x', 'main')")
    rid = c.execute("SELECT id FROM repos").fetchone()["id"]
    c.execute(
        "INSERT INTO fact_builds(repo_id, head_sha, built_at, duration_ms, counts, query_key)"
        " VALUES (?, 'abc', 'now', 1, '{}', 'k')",
        (rid,),
    )

    def define(path, name, start, end):
        stem = path.rsplit(".", 1)[0].replace("/", ".")
        c.execute(
            'INSERT INTO fact_defines(fact_id, repo_id, path, symbol, name, kind, start, "end",'
            " size, params, depth, branches, public) VALUES (?, ?, ?, ?, ?, 'function', ?, ?,"
            " ?, 0, 1, 0, 1)",
            (_id("def"), rid, path, f"{stem}.{name}", name, start, end, end - start + 1),
        )  # fmt: skip

    def call(caller, callee, path, line, resolved=1):
        c.execute(
            "INSERT INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path, line,"
            " resolved, callee_symbol) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (_id("call"), rid, caller, callee.rsplit(".", 1)[-1], path, line, resolved,
             callee if resolved else None),
        )  # fmt: skip

    def touch(sha, ts, symbol, path):
        c.execute(
            "INSERT INTO fact_touched(fact_id, repo_id, commit_sha, ts, symbol, path)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_id("tch"), rid, sha, ts, symbol, path),
        )  # fmt: skip

    define("src/cand_quiz.py", "main", 3, 12)
    define("src/cand_quiz.py", "alpha", 14, 18)
    define("src/cand_quiz.py", "beta", 20, 24)
    define("src/cand_quiz.py", "gamma", 26, 30)
    define("src/util.py", "helper", 1, 5)
    define("billing/invoice.py", "total", 1, 5)
    # main calls alpha first (line 5), then beta (7), then gamma (9)
    call("src.cand_quiz.main", "src.cand_quiz.beta", "src/cand_quiz.py", 7)
    call("src.cand_quiz.main", "src.cand_quiz.alpha", "src/cand_quiz.py", 5)
    call("src.cand_quiz.main", "src.cand_quiz.gamma", "src/cand_quiz.py", 9)
    # two callers of main
    call("src.util.helper", "src.cand_quiz.main", "src/util.py", 3)
    call("src.util.helper", "src.cand_quiz.main", "src/util.py", 4)
    touch(SHA_A, 100, "src.cand_quiz.main", "src/cand_quiz.py")
    touch(SHA_B, 200, "src.cand_quiz.main", "src/cand_quiz.py")
    touch(SHA_C, 150, "src.cand_quiz.alpha", "src/cand_quiz.py")
    yield c
    c.close()


# ---- brief ----


def _brief(conn):
    return build(count=60, packet_size=60, facts_conn=conn)


def _quiz_refs(b):
    return [
        r
        for pk in b.packets
        for r in pk.lead_refs
        if r.get("story_type") in ("quiz", "this_or_that") and r.get("seeds")
    ]


def test_quiz_slot_carries_fact_seed_with_ids_and_distractors(conn):
    b = _brief(conn)
    refs = _quiz_refs(b)
    assert refs, "no quiz lead got a seed"
    seeds = refs[0]["seeds"]
    assert 1 <= len(seeds) <= 2
    for s in seeds:
        assert s["seed"] in quizfacts.KINDS
        assert s["fact_ids"] and s["distractors"] and s["subject"]
        assert s["answer"] not in s["distractors"]
    first = next(s for s in seeds if s["seed"] == "first_call")
    assert first["answer"] == "alpha"
    assert set(first["distractors"]) <= {"beta", "gamma"}
    md = b.to_markdown()
    assert "answer_fact" in md and "first_call" in md


def test_no_facts_conn_means_no_seeds():
    b = build(count=60, packet_size=60)
    assert not any("seeds" in r for pk in b.packets for r in pk.lead_refs)


def test_seeds_only_for_quiz_like_stories(conn):
    b = _brief(conn)
    for pk in b.packets:
        for r in pk.lead_refs:
            if r.get("seeds"):
                assert r["story_type"] in ("quiz", "this_or_that", "guess_when")


# ---- validator ----


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def _card(fixture_repo, seed, subject, choices, idx, ids=None):
    card = C.quiz_card(fixture_repo)
    card["interaction"] = {
        "question": "Quick question about the code?",
        "choices": choices,
        "answer_index": idx,
        "explanation": "The facts store says so.",
        "answer_fact": {"seed": seed, "subject": subject, "fact_ids": ids or []},
    }
    return card


def _run(card, repos, conn):
    acc, rej = validator.validate_cards(
        [copy.deepcopy(card)], repos, V_PERSONAS, facts_conn=conn, claim_checks=False
    )
    return acc, [r.reason for r in rej]


def _ids(conn, sql):
    return [r["fact_id"] for r in conn.execute(sql)]


def test_correct_first_call_passes(fixture_repo, repos, conn):
    ids = _ids(conn, "SELECT fact_id FROM fact_calls WHERE callee_name = 'alpha'")
    c = _card(fixture_repo, "first_call", "main", ["beta", "alpha", "gamma"], 1, ids)
    acc, rej = _run(c, repos, conn)
    assert rej == [] and len(acc) == 1


def test_wrong_answer_index_is_rejected(fixture_repo, repos, conn):
    c = _card(fixture_repo, "first_call", "main", ["beta", "alpha", "gamma"], 0)
    assert _run(c, repos, conn)[1] == ["wrong_answer"]


def test_distractor_that_is_also_correct_is_ambiguous(fixture_repo, repos, conn):
    c = _card(fixture_repo, "calls_which", "main", ["alpha", "total", "beta"], 0)
    assert _run(c, repos, conn)[1] == ["ambiguous_answer"]


def test_invented_distractor_is_unreal(fixture_repo, repos, conn):
    c = _card(fixture_repo, "calls_which", "main", ["alpha", "total", "frobnicate"], 0)
    assert _run(c, repos, conn)[1] == ["distractor_unreal"]


def test_calls_which_correct_passes(fixture_repo, repos, conn):
    c = _card(fixture_repo, "calls_which", "main", ["helper", "gamma", "total"], 1)
    assert _run(c, repos, conn)[1] == []


def test_caller_count(fixture_repo, repos, conn):
    ok = _card(fixture_repo, "caller_count", "main", ["1 place", "2 places", "5 places"], 1)
    assert _run(ok, repos, conn)[1] == []
    bad = _card(fixture_repo, "caller_count", "main", ["1 place", "2 places", "5 places"], 2)
    assert _run(bad, repos, conn)[1] == ["wrong_answer"]


def test_introduced_in_matches_commit_prefix(fixture_repo, repos, conn):
    ok = _card(
        fixture_repo, "introduced_in", "main", [f"{SHA_C[:8]} later", f"{SHA_A[:7]} first"], 1
    )
    assert _run(ok, repos, conn)[1] == []
    bad = _card(fixture_repo, "introduced_in", "main", [SHA_B[:8], SHA_A[:7]], 0)
    assert _run(bad, repos, conn)[1] == ["wrong_answer"]
    fake = _card(fixture_repo, "introduced_in", "main", [SHA_A[:8], "deadbee0"], 0)
    assert _run(fake, repos, conn)[1] == ["distractor_unreal"]


def test_defined_in(fixture_repo, repos, conn):
    ok = _card(fixture_repo, "defined_in", "main", ["src/util.py", "src/cand_quiz.py"], 1)
    assert _run(ok, repos, conn)[1] == []
    fake = _card(fixture_repo, "defined_in", "main", ["src/cand_quiz.py", "src/nope.py"], 0)
    assert _run(fake, repos, conn)[1] == ["distractor_unreal"]


def test_unknown_fact_id_rejected(fixture_repo, repos, conn):
    c = _card(
        fixture_repo,
        "defined_in",
        "main",
        ["src/util.py", "src/cand_quiz.py"],
        1,
        ["def-ffffffffffff"],
    )
    assert _run(c, repos, conn)[1] == ["wrong_answer"]


def test_without_answer_fact_nothing_changes(fixture_repo, repos, conn):
    c = C.quiz_card(fixture_repo)
    assert _run(c, repos, conn)[1] == []


def test_schema_rejects_bad_seed(fixture_repo, repos, conn):
    c = _card(fixture_repo, "made_up", "main", ["a", "b"], 0)
    assert _run(c, repos, conn)[1] == ["schema"]
