"""Profile detector engine and scoring."""

import logging
import time

import pytest

from gittok import candidates, db, detectors, gitq, profiles, signals
from gittok.config import AnalysisSettings, Repo
from tests.fixture_repo import build_history_repo

ROUTES = """from flask import Flask

app = Flask(__name__)

# padding
# padding


@app.route("/invoices")
def invoices():
    return 1


def helper():
    return audit_log("x")


def other():
    return audit_log("y")
"""
BAD_LINE = "a" * 60 + "b"
FILES = {
    "app/routes.py": ROUTES,
    "app/core.py": "def thing():\n    return 1\n",
    "app/hack.py": "# HACK: temporary\n" + "x = 1\n" * 12,
    "app/evil.py": f"# {BAD_LINE}\nx = 1\n",
    "web/api.ts": "export function load() {\n  return fetch('/x');\n}\nfunction local() {}\n",
    "web/lib/out.ts": "export function generated() {}\n",
}

HAVE_ASTGREP = detectors.ast_grep_available()


def rule(id="audit", tag="audit_trail", **over):
    d = {
        "id": id,
        "tag": tag,
        "weight": 1,
        "match": {"regex": r"audit_log\((\"\w+\")\)", "paths": ["app/**"]},
    }
    d.update(over)
    return d


def profile(**data):
    return profiles.parse({"version": 1, **data}, "fixture")


@pytest.fixture(scope="module")
def repo_path(tmp_path_factory):
    steps = [("base", FILES, "2026-01-20T10:00:00+00:00")]
    return build_history_repo(tmp_path_factory.mktemp("det") / "repo", steps).path


def run(repo_path, prof=None, settings=None):
    t0 = gitq.commit_time(repo_path, "main")
    return candidates.mine(repo_path, "main", t0, {}, settings or AnalysisSettings(), profile=prof)


def by_rule(out, rid):
    return [c for c in out if c.get("rule_id") == rid]


def test_no_profile_is_unchanged(repo_path):
    plain = run(repo_path)
    assert run(repo_path, profiles.Profile()) == plain
    assert all(c.get("rule_id") is None for c in plain)


def test_regex_rule_makes_candidates(repo_path):
    out = run(repo_path, profile(detectors=[rule(why="audit {match} at line {line}")]))
    hits = by_rule(out, "audit")
    assert [(c["path"], c["tag"]) for c in hits] == [("app/routes.py", "audit_trail")] * 2
    first = sorted(hits, key=lambda c: c["start"])[0]
    assert first["why"] == 'audit "x" at line 15'
    assert first["start"] <= 15 <= first["end"] and first["end"] - first["start"] + 1 <= 20


def test_default_why_and_window_size(repo_path):
    out = run(repo_path, profile(detectors=[rule(window=5)]))
    c = sorted(by_rule(out, "audit"), key=lambda c: c["start"])[0]
    assert c["why"] == 'audit at line 15: return audit_log("x")'
    assert c["end"] - c["start"] + 1 == 5 and c["start"] == 13


def test_paths_and_exclude(repo_path):
    r = rule(match={"regex": r"def \w+", "paths": ["app/**"], "exclude": ["app/core.py"]})
    out = by_rule(run(repo_path, profile(detectors=[r])), "audit")
    paths = {c["path"] for c in out}
    assert "app/routes.py" in paths and "app/core.py" not in paths and "web/api.ts" not in paths


def test_language_restricts_regex_files(repo_path):
    r = rule(match={"regex": r"function \w+", "paths": ["**"], "language": "typescript"})
    out = by_rule(run(repo_path, profile(detectors=[r])), "audit")
    assert {c["path"] for c in out} == {"web/api.ts", "web/lib/out.ts"}


def test_per_file_cap_and_per_rule_limit(repo_path):
    r = rule(match={"regex": r"=|return|def ", "paths": ["app/**"]})
    out = by_rule(run(repo_path, profile(detectors=[r])), "audit")
    from collections import Counter

    assert max(Counter(c["path"] for c in out).values()) <= 3
    out = by_rule(
        run(repo_path, profile(detectors=[r]), AnalysisSettings(candidates_per_tag=2)), "audit"
    )
    assert len(out) == 2


def test_catastrophic_regex_times_out_without_failing(repo_path, caplog, monkeypatch):
    monkeypatch.setattr(detectors, "REGEX_TIMEOUT_S", 0.1)
    bad = rule("boom", match={"regex": r"(a|aa)+$", "paths": ["app/evil.py"]})
    good = rule("audit")
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="gittok.detectors"):
        out = run(repo_path, profile(detectors=[bad, good]))
    assert time.monotonic() - started < 10
    assert by_rule(out, "boom") == []
    assert by_rule(out, "audit")  # other rules still run
    assert any("boom" in r.message and "app/evil.py" in r.message for r in caplog.records)


def test_long_lines_are_skipped(repo_path, monkeypatch):
    monkeypatch.setattr(detectors, "MAX_LINE", 20)
    out = run(repo_path, profile(detectors=[rule(match={"regex": "aaa", "paths": ["app/**"]})]))
    assert by_rule(out, "audit") == []


def test_ignore_globs_drop_builtin_candidates(repo_path):
    plain = run(repo_path)
    assert any(c["path"] == "app/hack.py" for c in plain)
    out = run(repo_path, profile(ignore=["app/hack.py", "web/**"], detectors=[rule()]))
    assert not any(c["path"] in ("app/hack.py",) or c["path"].startswith("web/") for c in out)
    assert by_rule(out, "audit")


def test_ast_grep_rules_are_skipped_with_one_log_line_when_missing(repo_path, caplog, monkeypatch):
    monkeypatch.setattr(detectors, "ast_grep_available", lambda: False)
    rules = [
        rule(
            f"ast{i}",
            match={"ast_grep": "def $F($$$A): $$$B", "language": "python", "paths": ["app/**"]},
        )
        for i in range(2)
    ]
    with caplog.at_level(logging.INFO, logger="gittok.detectors"):
        out = run(repo_path, profile(detectors=rules + [rule()]))
    assert by_rule(out, "ast0") == [] and by_rule(out, "ast1") == []
    assert by_rule(out, "audit")
    skips = [r for r in caplog.records if "ast-grep" in r.message]
    assert len(skips) == 1


@pytest.mark.skipif(not HAVE_ASTGREP, reason="ast-grep-py not installed")
def test_ast_grep_rule_makes_candidates(repo_path):
    py = rule(
        "py-def",
        "defs",
        match={"ast_grep": "def $F($$$A): $$$B", "language": "python", "paths": ["app/routes.py"]},
        why="def {match}",
    )
    ts = rule(
        "ts-fn",
        "fns",
        match={
            "ast_grep": "export function $N($$$A) { $$$B }",
            "language": "typescript",
            "paths": ["web/**"],
        },
    )
    out = run(repo_path, profile(detectors=[py, ts]))
    defs = sorted(by_rule(out, "py-def"), key=lambda c: c["start"])
    assert defs[0]["why"] == "def def invoices():"
    assert len(defs) == 3 and defs[0]["tag"] == "defs"
    assert {c["path"] for c in by_rule(out, "ts-fn")} == {"web/api.ts", "web/lib/out.ts"}


@pytest.mark.skipif(not HAVE_ASTGREP, reason="ast-grep-py not installed")
def test_ast_grep_unsupported_language_is_skipped(repo_path, caplog):
    r = rule("clj", match={"ast_grep": "(defn $N)", "language": "clojure", "paths": ["**"]})
    with caplog.at_level(logging.INFO, logger="gittok.detectors"):
        out = run(repo_path, profile(detectors=[r, rule()]))
    assert by_rule(out, "clj") == [] and by_rule(out, "audit")
    assert any("clojure" in r.message for r in caplog.records)


def test_weight_scales_score_and_formula_is_documented_shape(repo_path):
    lo = by_rule(run(repo_path, profile(detectors=[rule(weight=1)])), "audit")
    hi = by_rule(run(repo_path, profile(detectors=[rule(weight=2.5)])), "audit")
    assert hi[0]["score"] == pytest.approx(lo[0]["score"] * 2.5, rel=1e-3)


def test_factors():
    assert candidates.fanin_factor(0) == 1.0
    assert candidates.fanin_factor(15) == pytest.approx(2.0)
    assert candidates.fanin_factor(10**6) == 2.0
    assert (
        candidates.size_factor(5) < candidates.size_factor(15) < candidates.size_factor(40) == 1.0
    )
    assert candidates.age_factor(True) == 1.0 and candidates.age_factor(False) < 1.0
    assert candidates.churn_factor(None) == 1.0
    assert candidates.churn_factor(0.5) == pytest.approx(1.25)
    assert candidates.churn_factor(1.0) == pytest.approx(1.5)


def test_refresh_stores_rule_id(repo_path, tmp_path):
    conn = db.open_db(tmp_path / "t.db")
    repo = Repo(name="fixture", path=repo_path, ref="main")
    res = signals.analyze(conn, repo, AnalysisSettings(), profile=profile(detectors=[rule()]))
    assert res["head_sha"]
    rows = candidates.load_candidates(conn, "fixture")
    assert {r["rule_id"] for r in rows} >= {None, "audit"}
    assert all(r["rule_id"] is None for r in rows if r["tag"] != "audit_trail")
    assert candidates.load_candidates(conn, "fixture", tag="audit_trail")[0]["rule_id"] == "audit"
    # a forced re-run without the rule removes its rows
    signals.analyze(conn, repo, AnalysisSettings(), force=True)
    assert candidates.load_candidates(conn, "fixture", tag="audit_trail") == []


def test_optional_first_group_does_not_crash(repo_path):
    r = rule("opt", match={"regex": r"^\s*(async )?def (\w+)\(", "paths": ["app/**"]})
    out = by_rule(run(repo_path, profile(detectors=[r])), "opt")
    assert out and all(c["path"].startswith("app/") for c in out)


def test_run_never_raises_on_a_bad_hit(repo_path, monkeypatch, caplog):
    real = detectors._hit

    def flaky(d, sf, line, text, match):
        if sf.path == "app/core.py":
            raise RuntimeError("boom")
        return real(d, sf, line, text, match)

    monkeypatch.setattr(detectors, "_hit", flaky)
    r = rule("flaky", match={"regex": r"def (\w+)", "paths": ["app/**"]})
    with caplog.at_level(logging.WARNING, logger="gittok.detectors"):
        out = by_rule(run(repo_path, profile(detectors=[r])), "flaky")
    assert out and all(c["path"] != "app/core.py" for c in out)
    assert any("app/core.py" in x.message for x in caplog.records)
