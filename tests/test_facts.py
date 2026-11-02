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
