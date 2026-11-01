"""Candidate miners: structure (2g0.5) and shape/smell/clever markers (2g0.6)."""

import pytest

from codescroll import candidates, db, gitq, signals
from codescroll.config import AnalysisSettings, Repo
from tests.fixture_repo import build_history_repo

CORE_PY = "def thing():\n    return 1\n"
DEEP_PY = """import re
import time

PATTERN = re.compile(r"^(\\d{3})-(\\d{4})$")


def tangled(a, b):
    for i in a:
        if i:
            for j in b:
                if j:
                    while j:
                        return 1
    # HACK: remove once upstream fixes the parser
    try:
        time.sleep(3)
    except:
        pass
    return 0


def countdown(n):
    if n == 0:
        return 0
    return countdown(n - 1)


def many(a, b, c, d, e, f, g):
    return a
"""
TEST_DEEP = """import pytest


@pytest.mark.skip(reason="flaky")
def test_tangled():
    assert True
"""
ROUTES_PY = """from flask import Flask
from app import auth, core, db, models, util

app = Flask(__name__)


@app.route("/invoices")
def invoices():
    return core.thing()
"""
HANDLER_CLJ = """(ns my.app.handler
  (:require [my.app.core :as core]
            [my.app.util :as util]))

(defroutes app-routes
  (GET "/x" [] (core/thing)))

(defmacro unless [c & body]
  `(if ~c nil (do ~@body)))
"""
SERVER_TS = """import { thing } from '../../lib/core';

export async function GET() {
  return new Response(String(thing()));
}
"""


@pytest.fixture(scope="module")
def repo_path(tmp_path_factory):
    old = "2024-01-01T10:00:00+00:00"
    base = {
        "app/__init__.py": "",
        "app/core.py": CORE_PY,
        "app/util.py": "from .core import thing\n",
        "app/db.py": "from app.core import thing\n",
        "app/models.py": "from app import core\n",
        "app/auth.py": "import app.core\n",
        "my/app/core.clj": "(ns my.app.core)\n(defn thing [] 1)\n(defn- hidden [] 2)\n",
        "my/app/util.clj": "(ns my.app.util\n  (:require [my.app.core :as core]))\n",
        "web/lib/core.ts": "export function thing() { return 1 }\n",
    }
    steps = [("old base", base, old)]
    for i in range(3):  # tests and deep.py change together
        steps.append(
            (
                f"deep {i}",
                {
                    "app/deep.py": DEEP_PY + f"\nV = {i}\n",
                    "tests/test_deep.py": TEST_DEEP + f"\nV = {i}\n",
                },
                f"2025-{10 + i}-15T10:00:00+00:00",
            )
        )
    steps.append(
        (
            "routes",
            {
                "app/routes.py": ROUTES_PY,
                "my/app/handler.clj": HANDLER_CLJ,
                "web/routes/api/+server.ts": SERVER_TS,
                "web/routes/other.ts": "import { thing } from '$lib/core';\nthing();\n",
            },
            "2026-01-20T10:00:00+00:00",
        )
    )
    return build_history_repo(tmp_path_factory.mktemp("cand") / "repo", steps).path


@pytest.fixture(scope="module")
def mined(repo_path):
    t0 = gitq.commit_time(repo_path, "main")
    commits = signals.parse_log(repo_path, "main")
    sig = {"co_change": signals.co_change(commits)}
    return candidates.mine(repo_path, "main", t0, sig, AnalysisSettings())


def find(mined, tag, path=None):
    return [c for c in mined if c["tag"] == tag and (path is None or c["path"] == path)]


def test_route_file_is_entry_point(mined):
    hits = find(mined, "entry_point")
    paths = {c["path"] for c in hits}
    assert "app/routes.py" in paths  # python decorator
    assert "my/app/handler.clj" in paths  # clojure defroutes
    assert "web/routes/api/+server.ts" in paths  # sveltekit handler


def test_core_is_module_required_by_most(mined):
    core = [c["path"] for c in find(mined, "core")]
    assert core[0] == "app/core.py"
    assert "my/app/core.clj" in core
    assert "web/lib/core.ts" in core  # via the $lib alias
    assert "5 files" in find(mined, "core", "app/core.py")[0]["why"]


def test_god_file_has_high_fan_out(repo_path):
    from pathlib import Path

    from codescroll.config import load_languages

    spec = load_languages(Path(__file__).parents[1])
    spec["languages"]["python"]["thresholds"]["god_fan_out"] = 5  # the fixture is small
    t0 = gitq.commit_time(repo_path, "main")
    out = candidates.mine(repo_path, "main", t0, {}, AnalysisSettings(), languages=spec)
    assert [c["path"] for c in find(out, "god_file")] == ["app/routes.py"]


def test_public_api_skips_private_defs(mined):
    clj = find(mined, "public_api", "my/app/core.clj")[0]
    assert "thing" in clj["why"] and "hidden" not in clj["why"]
    assert find(mined, "public_api", "app/core.py")


def test_hack_comment(mined):
    c = find(mined, "smell", "app/deep.py")[0]
    assert "HACK" in c["why"] and "remove once upstream" in c["why"]
    assert c["start"] <= 14 <= c["end"] and c["end"] - c["start"] < 40


def test_deep_nesting_names_line(mined):
    c = find(mined, "deep_nesting", "app/deep.py")[0]
    assert "nesting depth 6" in c["why"] and "line 13" in c["why"]
    assert c["start"] <= 13 <= c["end"]


def test_regex_literal_is_clever(mined):
    c = [c for c in find(mined, "clever", "app/deep.py") if "regex" in c["why"]][0]
    assert "line 4" in c["why"]


def test_skipped_test(mined):
    c = find(mined, "skipped_test")[0]
    assert c["path"] == "tests/test_deep.py" and "line 4" in c["why"]


def test_catch_all_sleep_params_recursion(mined):
    assert "line 17" in find(mined, "catch_all", "app/deep.py")[0]["why"]
    assert "line 16" in find(mined, "sleep", "app/deep.py")[0]["why"]
    assert "7 parameters" in find(mined, "many_params", "app/deep.py")[0]["why"]
    assert any("recurs" in c["why"] for c in find(mined, "clever", "app/deep.py"))


def test_clojure_macro_is_clever(mined):
    assert any("defmacro" in c["why"] for c in find(mined, "clever", "my/app/handler.clj"))


def test_stable_core_and_well_tested(mined):
    stable = [c["path"] for c in find(mined, "stable_core")]
    assert "app/core.py" in stable and "app/deep.py" not in stable
    wt = find(mined, "well_tested", "app/deep.py")[0]
    assert "tests/test_deep.py" in wt["why"] and "jaccard 1.00" in wt["why"]


def test_long_function_and_line(tmp_path):
    body = "".join(f"    x{i} = {i}\n" for i in range(70))
    long_line = "    y = '" + "a" * 200 + "'\n"
    r = build_history_repo(
        tmp_path / "r",
        [
            (
                "one",
                {"m.py": f"def big():\n{body}{long_line}    return 1\n"},
                "2026-01-01T10:00:00+00:00",
            )
        ],
    )
    t0 = gitq.commit_time(r.path, "main")
    out = candidates.mine(r.path, "main", t0, {}, AnalysisSettings())
    lf = find(out, "long_function")[0]
    assert "73 lines" in lf["why"] and lf["end"] - lf["start"] < 40
    assert "line 72 is 210 characters" in find(out, "long_line")[0]["why"]


def test_skips_vendored_generated_lockfiles_and_big_files(tmp_path):
    hack = "# HACK: nope\nx = 1\n"
    files = {
        "node_modules/a/index.js": "// HACK: nope\n",
        "vendor/x.py": hack,
        "gen.py": "# @generated do not edit\n" + hack,
        "uv.lock": hack,
        "big.py": hack + "y = 2\n" * 5000,
        "ok.py": hack,
    }
    r = build_history_repo(tmp_path / "r", [("one", files, "2026-01-01T10:00:00+00:00")])
    t0 = gitq.commit_time(r.path, "main")
    out = candidates.mine(r.path, "main", t0, {}, AnalysisSettings(candidate_max_file_bytes=10000))
    assert {c["path"] for c in find(out, "smell")} == {"ok.py"}


def test_per_tag_limit(tmp_path):
    files = {f"m{i}.py": "# HACK: x\n" for i in range(10)}
    r = build_history_repo(tmp_path / "r", [("one", files, "2026-01-01T10:00:00+00:00")])
    t0 = gitq.commit_time(r.path, "main")
    out = candidates.mine(r.path, "main", t0, {}, AnalysisSettings(candidates_per_tag=3))
    assert len(find(out, "smell")) == 3


def test_shipped_languages_file_loads():
    from pathlib import Path

    from codescroll.config import load_languages

    spec = load_languages(Path(__file__).parents[1])
    assert {"python", "clojure", "typescript"} <= set(spec["languages"])


def test_unknown_language_gives_nothing(tmp_path):
    r = build_history_repo(
        tmp_path / "r", [("one", {"a.zig": "// HACK: x\n"}, "2026-01-01T10:00:00+00:00")]
    )
    t0 = gitq.commit_time(r.path, "main")
    assert candidates.mine(r.path, "main", t0, {}, AnalysisSettings()) == []


def test_analyze_stores_and_load_candidates(repo_path):
    conn = db.connect(":memory:")
    db.migrate(conn)
    repo = Repo(name="cand", path=repo_path, ref="main")
    signals.analyze(conn, repo, AnalysisSettings())
    rows = candidates.load_candidates(conn, "cand")
    assert rows and {"path", "start", "end", "tag", "why", "score"} <= set(rows[0])
    cores = candidates.load_candidates(conn, "cand", tag="core", limit=1)
    assert [r["path"] for r in cores] == ["app/core.py"]
    # a second pass keeps first_seen and does not duplicate rows
    n = conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
    signals.analyze(conn, repo, AnalysisSettings(), force=True)
    assert conn.execute("SELECT count(*) FROM candidates").fetchone()[0] == n
