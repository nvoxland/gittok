"""Cards list the facts they rely on."""

import pytest

from codescroll import db, validator
from codescroll.config import AgentSettings, Repo
from tests.cards import example_card, explain
from tests.test_validator import PERSONAS


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
    c.execute(
        'INSERT INTO fact_defines(fact_id, repo_id, path, symbol, name, kind, start, "end",'
        " size, params, depth, branches, public) VALUES ('def-aaaaaaaaaaaa', ?,"
        " 'billing/invoice.py', 'billing.invoice.total', 'total', 'function', 1, 5, 5, 1, 1, 0, 1)",
        (rid,),
    )
    c.execute(
        "INSERT INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path, line,"
        " resolved, callee_symbol) VALUES ('call-111111111111', ?, 'billing.invoice.total',"
        " 'helper', 'billing/invoice.py', 3, 1, 'billing.invoice.helper')",
        (rid,),
    )
    c.execute(
        "INSERT INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path, line,"
        " resolved, callee_symbol) VALUES ('call-222222222222', ?, 'billing.invoice.total',"
        " 'mystery', 'billing/invoice.py', 4, 0, NULL)",
        (rid,),
    )
    c.execute(
        "INSERT INTO fact_touched(fact_id, repo_id, commit_sha, ts, symbol, path)"
        " VALUES ('tch-333333333333', ?, 'deadbeefcafe1234', 5, 'billing.invoice.total',"
        " 'billing/invoice.py')",
        (rid,),
    )
    c.execute(
        "INSERT INTO fact_imports(fact_id, repo_id, path, line, module_text, resolved_path)"
        " VALUES ('imp-444444444444', ?, 'billing/invoice.py', 1, 'decimal', NULL)",
        (rid,),
    )
    yield c
    c.close()


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def run(card, repos, conn, require=False):
    # claim checks off: they would reject an unknown name in the explain before facts are looked at
    return validator.validate_cards(
        [card], repos, PERSONAS, facts_conn=conn, require_facts=require, claim_checks=False
    )


def card_with(fixture_repo, fs, **kw):
    return example_card(fixture_repo, facts=fs, **kw)


def test_true_calls_fact_passes_and_stores_id(fixture_repo, repos, conn):
    c = card_with(fixture_repo, [{"calls": ["total", "helper"]}])
    acc, rej = run(c, repos, conn)
    assert rej == []
    assert acc[0].resolved["facts"] == ["call-111111111111"]


def test_fact_id_passes(fixture_repo, repos, conn):
    acc, rej = run(card_with(fixture_repo, ["def-aaaaaaaaaaaa"]), repos, conn)
    assert rej == [] and acc[0].resolved["facts"] == ["def-aaaaaaaaaaaa"]


def test_typed_kinds(fixture_repo, repos, conn):
    fs = [
        {"defines": ["billing/invoice.py", "total"]},
        {"touched": ["deadbee", "total"]},
        {"params": ["total", 1]},
        {"imports": ["billing/invoice.py", "decimal"]},
    ]
    acc, rej = run(card_with(fixture_repo, fs), repos, conn)
    assert rej == []
    assert acc[0].resolved["facts"] == [
        "def-aaaaaaaaaaaa", "tch-333333333333", "imp-444444444444"
    ]  # fmt: skip


def test_unresolved_call_matches_by_callee_name(fixture_repo, repos, conn):
    acc, rej = run(card_with(fixture_repo, [{"calls": ["total", "mystery"]}]), repos, conn)
    assert rej == []
    assert acc[0].resolved["facts"] == ["call-222222222222"]
    assert any("unresolved" in w for w in acc[0].warnings)


@pytest.mark.parametrize(
    "bad",
    [
        {"calls": ["total", "nope"]},
        {"calls": ["helper", "total"]},
        {"params": ["total", 3]},
        {"defines": ["other.py", "total"]},
        {"touched": ["0000000", "total"]},
        "call-999999999999",
        "zzz-000000000000",
    ],
)
def test_false_fact_rejected(fixture_repo, repos, conn, bad):
    acc, rej = run(card_with(fixture_repo, [bad]), repos, conn)
    assert acc == [] and [r.reason for r in rej] == ["fact_false"]


def test_facts_without_store_rejected(fixture_repo, repos):
    acc, rej = run(card_with(fixture_repo, [{"calls": ["total", "helper"]}]), repos, None)
    assert [r.reason for r in rej] == ["fact_false"]


def test_schema_rejects_bad_shape(fixture_repo, repos, conn):
    acc, rej = run(card_with(fixture_repo, [{"calls": ["a"]}]), repos, conn)
    assert [r.reason for r in rej] == ["schema"]


def _unbacked(fixture_repo, **kw):
    text = explain("round(t)") + "\n\nIt also leans on `quantum_flux` somewhere."
    c = example_card(fixture_repo, **kw)
    c["depth"][0]["text"] = text
    return c


def test_require_facts_rejects_unbacked_identifier(fixture_repo, repos, conn):
    acc, rej = run(_unbacked(fixture_repo), repos, conn, require=True)
    assert [r.reason for r in rej] == ["fact_missing"]
    assert "quantum_flux" in rej[0].detail


def test_require_facts_off_warns(fixture_repo, repos, conn):
    acc, rej = run(_unbacked(fixture_repo), repos, conn, require=False)
    assert rej == []
    assert any("quantum_flux" in w for w in acc[0].warnings)


def test_fact_covers_identifier(fixture_repo, repos, conn):
    c = _unbacked(fixture_repo, facts=[{"calls": ["total", "helper"]}])
    c["depth"][0]["text"] = c["depth"][0]["text"].replace("quantum_flux", "helper()")
    acc, rej = run(c, repos, conn, require=True)
    assert rej == [] and acc[0].warnings == []


def test_cited_code_covers_identifier(fixture_repo, repos, conn):
    acc, rej = run(example_card(fixture_repo), repos, conn, require=True)
    assert rej == []


def test_default_setting_off():
    assert AgentSettings().require_facts is False
