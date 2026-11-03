"""The syntax facts store."""

import re
from pathlib import Path

import pytest

from codescroll import db, facts, gitq, signals, structure
from codescroll.config import AnalysisSettings, Repo
from tests.fixture_repo import build_history_repo

needs_grammars = pytest.mark.skipif(
    not (structure.available() and structure.ready("python") and structure.ready("typescript")),
    reason="needs `uv sync --group structure` and its grammars",
)

UTIL1 = "def parse(s, sep, strict):\n    return s.split(sep)\n\n\ndef helper():\n    return 1\n"
UTIL2 = "def parse(s, sep, strict):\n    return s.split(sep, 1)\n\n\ndef helper():\n    return 1\n"
APP = "from util import parse\n\n\ndef main():\n    return parse('a', ',', True)\n"
A = "def run():\n    return 1\n"
B = "def run():\n    return 2\n"
GO = "def go():\n    return run()\n"
TS_LIB = "export function twice(n: number) { return n * 2; }\n"
TS_USE = "import { twice } from './lib';\nexport function four() { return twice(2); }\n"
D1 = "2026-01-01T10:00:00+00:00"
D2 = "2026-01-02T10:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def repo(tmp_path):
    steps = [
        ("one", {"util.py": UTIL1, "app.py": APP, "a.py": A, "b.py": B, "go.py": GO}, D1),
        ("two", {"util.py": UTIL2, "web/lib.ts": TS_LIB, "web/use.ts": TS_USE}, D2),
    ]
    return build_history_repo(tmp_path / "r", steps)


def refresh(conn, r, force=False, settings=None, ids=None):
    head, t0 = ids or (gitq.rev_parse(r.path, "main"), gitq.commit_time(r.path, "main"))
    conn.execute(
        "INSERT OR IGNORE INTO repos(name, path, ref) VALUES ('fx', ?, 'main')", (str(r.path),)
    )
    return facts.refresh(conn, "fx", r.path, head, t0, settings or AnalysisSettings(), force=force)


@needs_grammars
def test_definition_params_size_and_id(conn, repo):
    refresh(conn, repo)
    (d,) = facts.definitions(conn, "fx", "parse")
    assert d["path"] == "util.py" and d["kind"] == "function"
    assert (d["start"], d["end"], d["params"]) == (1, 2, 3)
    assert d["source"] == "syntax" and d["size"] == 2
    assert re.fullmatch(r"def-[0-9a-f]{12}", d["fact_id"])
    assert facts.get(conn, d["fact_id"])["symbol"] == d["symbol"]


@needs_grammars
def test_callers_callees_resolved_through_imports(conn, repo):
    refresh(conn, repo)
    (d,) = facts.definitions(conn, "fx", "parse")
    (c,) = facts.callers(conn, "fx", d["symbol"])
    assert c["path"] == "app.py" and c["resolved"] == 1 and c["line"] == 5
    (main,) = facts.definitions(conn, "fx", "main")
    assert [x["callee_symbol"] for x in facts.callees(conn, "fx", main["symbol"])] == [d["symbol"]]


@needs_grammars
def test_ambiguous_short_name_is_unresolved(conn, repo):
    refresh(conn, repo)
    (go,) = facts.definitions(conn, "fx", "go")
    (c,) = facts.callees(conn, "fx", go["symbol"])
    assert c["callee_name"] == "run" and c["resolved"] == 0 and c["callee_symbol"] is None


@needs_grammars
def test_relative_import_resolves(conn, repo):
    refresh(conn, repo)
    imps = facts.imports(conn, "fx", "web/use.ts")
    assert imps and imps[0]["resolved_path"] == "web/lib.ts"
    (tw,) = facts.definitions(conn, "fx", "twice")
    assert [c["path"] for c in facts.callers(conn, "fx", tw["symbol"])] == ["web/use.ts"]


@needs_grammars
def test_history_last_changed_and_introduced(conn, repo):
    refresh(conn, repo)
    (d,) = facts.definitions(conn, "fx", "parse")
    h = facts.history(conn, "fx", d["symbol"])
    assert h["last_changed"]["commit_sha"] == repo.shas["1"]
    assert h["introduced"]["commit_sha"] == repo.shas["0"]
    (helper,) = facts.definitions(conn, "fx", "helper")
    assert (
        facts.history(conn, "fx", helper["symbol"])["last_changed"]["commit_sha"] == repo.shas["0"]
    )


@needs_grammars
def test_facts_in_lines(conn, repo):
    refresh(conn, repo)
    got = facts.facts_in(conn, "fx", "app.py", 4, 5)
    assert {f["fact_id"].split("-")[0] for f in got} == {"def", "call"}


@needs_grammars
def test_second_refresh_at_same_head_does_no_work(conn, repo, monkeypatch):
    first = refresh(conn, repo)
    assert first["built"] is True and first["counts"]["defines"] > 0
    ids = (repo.shas["1"], gitq.commit_time(repo.path, "main"))
    monkeypatch.setattr(structure, "parse", lambda *a, **k: pytest.fail("parsed again"))
    calls = []
    real = gitq.run_bytes
    monkeypatch.setattr(gitq, "run_bytes", lambda *a, **k: calls.append(a) or real(*a, **k))
    assert refresh(conn, repo, ids=ids)["built"] is False
    assert not calls


@needs_grammars
def test_force_replaces_rows(conn, repo):
    refresh(conn, repo)
    n = conn.execute("SELECT COUNT(*) FROM fact_defines").fetchone()[0]
    assert refresh(conn, repo, force=True)["built"] is True
    assert conn.execute("SELECT COUNT(*) FROM fact_defines").fetchone()[0] == n


@needs_grammars
def test_caps_limit_commits_and_defs(conn, repo):
    refresh(conn, repo, settings=AnalysisSettings(facts_max_commits=1, facts_max_defs=3))
    assert conn.execute("SELECT COUNT(*) FROM fact_defines").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(DISTINCT commit_sha) FROM fact_touched").fetchone()[0] <= 1


@needs_grammars
def test_analyze_builds_facts(conn, repo):
    signals.analyze(conn, Repo(name="fx", path=repo.path, ref="main"), AnalysisSettings())
    assert conn.execute("SELECT COUNT(*) FROM fact_defines").fetchone()[0] > 0


def test_no_layer_means_no_build(conn, repo, monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)
    assert refresh(conn, repo)["built"] is False


def test_facts_module_names_no_language():
    src = Path(facts.__file__).read_text().lower()
    names = [
        "python", "clojure", "typescript", "javascript", "golang", "ruby", "java", "rust",
        "svelte", "tsx", "kotlin", "swift", "php", "scala", "haskell", "elixir",
    ]  # fmt: skip
    for n in names:
        assert not re.search(rf"\b{n}\b", src), n
    assert not re.search(r"""["']\.(py|clj|ts|js|go|rb|rs)["']""", src)


# ---------- agent-supplied analyzer facts ----------

SRC = "def parse(s, sep):\n    return s.split(sep)\n\n\ndef main():\n    return parse('a', ',')\n"
AC = "analyzer:lint 1.0"


@pytest.fixture
def arepo(tmp_path, conn):
    r = build_history_repo(tmp_path / "ar", [("one", {"m.txt": SRC, "n.txt": "import os\n"}, D1)])
    conn.execute("INSERT INTO repos(name, path, ref) VALUES ('fx', ?, 'main')", (str(r.path),))
    r.head = gitq.rev_parse(r.path, "main")
    return r


def submit(conn, r, items, head=None, tool="lint 1.0", current=None):
    return facts.submit_analyzer(conn, "fx", r.path, current or r.head, head or r.head, tool, items)


def rows(conn, table):
    return [dict(x) for x in conn.execute(f"SELECT * FROM {table}")]


def dfn(name, line, end=None):
    return {"defines": {"path": "m.txt", "name": name, "line": line, "end_line": end or line}}


def call(line, caller, callee, **kw):
    return {"calls": {"path": "m.txt", "line": line, "caller": caller, "callee": callee, **kw}}


def test_matching_facts_are_stored_with_analyzer_source(conn, arepo):
    got = submit(
        conn,
        arepo,
        [
            dfn("parse", 1, 2),
            dfn("main", 5, 6),
            call(6, "main", "parse", callee_path="m.txt"),
            {"imports": {"path": "n.txt", "line": 1, "module": "os"}},
            {"returns": {"path": "m.txt", "line": 1, "symbol": "parse", "type": "list"}},
            {"accepts": {"path": "m.txt", "line": 2, "symbol": "sep", "params": ["s"]}},
        ],
    )
    assert got["accepted"] == {"defines": 2, "calls": 1, "imports": 1, "returns": 1, "accepts": 1}
    assert got["rejected"] == []
    assert {r["source"] for r in rows(conn, "fact_defines")} == {AC}
    (c,) = rows(conn, "fact_calls")
    assert c["source"] == AC and c["resolved"] == 1
    assert c["callee_symbol"] == "m.txt:parse" and c["caller_symbol"] == "m.txt:main"
    assert {r["source"] for r in rows(conn, "fact_schema")} == {"schema:lint 1.0"}
    assert rows(conn, "fact_imports")[0]["module_text"] == "os"
    (a,) = rows(conn, "fact_analyzers")
    assert a["tool"] == "lint 1.0" and a["head_sha"] == arepo.head


def test_call_whose_callee_is_not_on_the_line_is_rejected(conn, arepo):
    got = submit(conn, arepo, [call(6, "main", "nope")])
    assert got["accepted"] == {}
    assert got["rejected"][0]["fact"] == "calls" and "nope" in got["rejected"][0]["reason"]
    assert rows(conn, "fact_calls") == []


def test_stale_head_is_rejected(conn, arepo):
    with pytest.raises(facts.FactsError, match="stale"):
        submit(conn, arepo, [], head="0" * 40)
    with pytest.raises(facts.FactsError, match="stale"):
        submit(conn, arepo, [], current="1" * 40)


def test_missing_path_and_bad_line_are_rejected(conn, arepo):
    gone = {"defines": {"path": "gone.txt", "name": "x", "line": 1}}
    got = submit(conn, arepo, [gone, dfn("parse", 99), dfn("other", 1), {"bogus": {}}])
    assert got["accepted"] == {} and got["rejected_count"] == 4


def test_caller_must_match_enclosing_definition(conn, arepo):
    submit(conn, arepo, [dfn("main", 5, 6)])
    got = submit(conn, arepo, [call(6, "wrong", "parse")])
    assert got["accepted"] == {} and "main" in got["rejected"][0]["reason"]


def test_analyzer_call_supersedes_unresolved_syntax_call(conn, arepo):
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    conn.execute(
        "INSERT INTO fact_defines VALUES ('def-aaaaaaaaaaaa', ?, 'm.txt', 'm.txt:main', 'main',"
        " 'function', 5, 6, 2, 0, 0, 0, 1, 'syntax')", (rid,)
    )  # fmt: skip
    conn.execute(
        "INSERT INTO fact_calls VALUES ('call-aaaaaaaaaaaa', ?, 'm.txt:main', 'parse', 'm.txt',"
        " 6, 0, NULL, 'syntax')", (rid,)
    )  # fmt: skip
    got = submit(conn, arepo, [call(6, "main", "parse", callee_path="m.txt")])
    assert got["accepted"] == {"calls": 1}
    (c,) = rows(conn, "fact_calls")
    assert c["resolved"] == 1 and c["callee_symbol"] == "m.txt:parse"
    assert c["source"] == AC and c["caller_symbol"] == "m.txt:main"


def test_chunks_add_and_a_resubmit_does_not_duplicate(conn, arepo):
    submit(conn, arepo, [dfn("parse", 1)])
    imp = {"imports": {"path": "n.txt", "line": 1, "module": "os"}}
    submit(conn, arepo, [dfn("parse", 1), imp])
    assert len(rows(conn, "fact_defines")) == 1
    (a,) = rows(conn, "fact_analyzers")
    assert db.loads(a["counts"])["imports"] == 1


def test_too_many_facts_in_one_call_is_an_error(conn, arepo):
    with pytest.raises(facts.FactsError, match="at most"):
        submit(conn, arepo, [{"x": 1}] * (facts.MAX_SUBMIT + 1))


def test_refresh_at_new_head_drops_analyzer_facts_and_hint_says_stale(conn, arepo, monkeypatch):
    submit(conn, arepo, [dfn("parse", 1)])
    assert facts.stale_analyzer_repos(conn, {"fx": arepo.head}) == []
    assert facts.stale_analyzer_repos(conn, {"fx": "2" * 40}) == ["fx"]
    monkeypatch.setattr(structure, "available", lambda: True)
    monkeypatch.setattr(facts, "_build", lambda *a: facts._Built())
    facts.refresh(conn, "fx", arepo.path, "2" * 40, 0, AnalysisSettings())
    assert rows(conn, "fact_defines") == []
    assert facts.stale_analyzer_repos(conn, {"fx": "2" * 40}) == ["fx"]
    assert "stale for fx" in facts.analyzer_hint(["fx"])
    assert facts.analyzer_hint([]) is None


def _syntax_rows(conn):
    """Syntax facts as the structure layer writes them: a qualified symbol, a kind of its own,
    and a callee name with the module alias still on it."""
    rid = conn.execute("SELECT id FROM repos").fetchone()[0]
    for sym, name, start, end in (("mod/parse", "parse", 1, 2), ("mod/main", "main", 5, 6)):
        conn.execute(
            "INSERT INTO fact_defines VALUES (?, ?, 'm.txt', ?, ?, 'function', ?, ?, 2, 0, 0, 0,"
            " 1, 'syntax')", (f"def-{name}", rid, sym, name, start, end)
        )  # fmt: skip
    conn.execute(
        "INSERT INTO fact_calls VALUES ('call-bbbbbbbbbbbb', ?, 'mod/main', 'm/parse', 'm.txt',"
        " 6, 1, 'mod/parse', 'syntax')", (rid,)
    )  # fmt: skip


def test_analyzer_define_reuses_syntax_symbol_whatever_its_kind_label(conn, arepo):
    """An analyzer says kind 'defn', the syntax layer
    'function'; the analyzer row got a new path:name symbol and both rows stayed."""
    _syntax_rows(conn)
    got = submit(
        conn, arepo, [{"defines": {"path": "m.txt", "name": "main", "line": 5, "kind": "defn"}}]
    )
    assert got["accepted"] == {"defines": 1}
    mains = [r for r in rows(conn, "fact_defines") if r["name"] == "main"]
    assert len(mains) == 1
    assert mains[0]["symbol"] == "mod/main" and mains[0]["source"] == AC


def test_analyzer_call_replaces_syntax_call_whose_name_carries_an_alias(conn, arepo):
    _syntax_rows(conn)
    got = submit(conn, arepo, [call(6, "main", "parse", callee_path="m.txt")])
    assert got["accepted"] == {"calls": 1}
    (c,) = rows(conn, "fact_calls")
    assert c["source"] == AC
    assert c["caller_symbol"] == "mod/main" and c["callee_symbol"] == "mod/parse"
