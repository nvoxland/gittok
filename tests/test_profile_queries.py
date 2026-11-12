"""Profile `queries` through save_profile and survey_repo."""

import pytest
import yaml

from blamescroll import structure
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo
from tests.test_profiling import FILES, call, data, profile_file

pytestmark = pytest.mark.anyio

GO_QUERY = "(function_declaration name: (identifier) @name) @definition.function"
needs_grammars = pytest.mark.skipif(
    not (structure.available() and structure.ready("go") and structure.ready("rust")),
    reason="needs tree-sitter grammars (structure --prefetch)",
)


@pytest.fixture
def cfg_go(tmp_path):
    files = {**FILES, "svc/main.go": "package main\n\nfunc Run() {}\n"}
    repo = build_history_repo(tmp_path / "r", [("base", files, "2026-01-20T10:00:00+00:00")])
    return make_config(repo, tmp_path / "cs")


async def save(cfg, profile):
    return data(await call(cfg, "save_profile", {"repo": "fixture", "profile": profile}))


@needs_grammars
async def test_save_profile_runs_and_reports_a_query(cfg_go):
    res = await save(cfg_go, {"queries": {"go": GO_QUERY}})
    assert res["ok"] and res["queries"] == {"go": {"files": 1, "defs": 1}}
    assert cfg_go.profile("fixture").queries == {"go": GO_QUERY}
    assert yaml.safe_load(profile_file(cfg_go).read_text())["queries"] == {"go": GO_QUERY}


@needs_grammars
@pytest.mark.parametrize(
    "bad", ["(function_declaration name: (nope) @name)", "(identifier) @bogus", "((("]
)
async def test_save_profile_refuses_a_query_that_does_not_compile(cfg_go, bad):
    res = await save(cfg_go, {"queries": {"go": bad}})
    assert not res["ok"] and "queries.go" in res["errors"]
    assert not profile_file(cfg_go).exists()


@needs_grammars
async def test_save_profile_refuses_a_query_for_a_grammar_no_file_uses(cfg_go):
    q = "(function_item name: (identifier) @name) @definition.function"
    res = await save(cfg_go, {"queries": {"rust": q}})
    assert not res["ok"] and "read no file" in res["errors"]["queries.rust"][0]


async def test_survey_says_what_structure_covers(cfg_go):
    out = data(await call(cfg_go, "survey_repo", {"repo": "fixture"}))
    assert "installed" in out["structure"] and "python" in out["structure"]["note"]
    assert out["languages"]["go"] == 2  # vendor/a.go and svc/main.go: a language with a query
