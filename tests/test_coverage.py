"""The survey's coverage table: for each language of a repo, what GitTok can use for it (a
grammar, a tags query, regex patterns, an analyzer from config/analyzers.yaml) and what it
lacks. The profiling skill works through the gaps, so no language is a special case."""

import shutil

import pytest

from gittok import overlay
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo
from tests.test_profiling import FILES, call, data

pytestmark = pytest.mark.anyio


@pytest.fixture
def cfg(tmp_path):
    repo = build_history_repo(tmp_path / "r", [("base", FILES, "2026-01-20T10:00:00+00:00")])
    return make_config(repo, tmp_path / "cs")


@pytest.fixture
def path_has(monkeypatch):
    """Fake PATH: the binaries that `shutil.which` finds."""
    found: set[str] = set()
    monkeypatch.setattr(
        shutil, "which", lambda name, *a, **k: f"/bin/{name}" if name in found else None
    )
    return found


def _rows(out):
    return {r["language"]: r for r in out["coverage"]}


async def test_survey_has_a_coverage_row_per_language_most_files_first(cfg, path_has):
    out = data(await call(cfg, "survey_repo", {"repo": "fixture"}))
    langs = [r["language"] for r in out["coverage"]]
    assert "python" in langs and "typescript" in langs and "other" not in langs
    counts = [r["files"] for r in out["coverage"]]
    assert counts == sorted(counts, reverse=True)
    py = _rows(out)["python"]
    assert py["files"] == out["languages"]["python"]
    assert py["query"] == "shipped" and py["patterns"] is True


async def test_an_analyzer_that_can_run_is_ready(cfg, path_has):
    out = data(await call(cfg, "survey_repo", {"repo": "fixture"}))
    py = _rows(out)["python"]
    assert [a["ready"] for a in py["analyzers"] if a["name"] == "python-ast"] == [False]
    assert "analyzer" in " ".join(py["gaps"])
    path_has.add("python3")
    out = data(await call(cfg, "survey_repo", {"repo": "fixture"}))
    py = _rows(out)["python"]
    ast_row = next(a for a in py["analyzers"] if a["name"] == "python-ast")
    assert ast_row["ready"] is True and "defines" in ast_row["gives"]
    assert not any("analyzer" in g for g in py["gaps"])


async def test_a_language_with_no_analyzer_in_the_catalog_says_so(cfg, path_has, monkeypatch):
    real = overlay.data

    def no_catalog(name):
        return {"analyzers": []} if name == "analyzers" else real(name)

    monkeypatch.setattr(overlay, "data", no_catalog)
    out = data(await call(cfg, "survey_repo", {"repo": "fixture"}))
    py = _rows(out)["python"]
    assert py["analyzers"] == []
    assert any("no analyzer" in g for g in py["gaps"])


def test_the_shipped_catalog_is_valid_and_covers_the_shipped_query_languages():
    cat = overlay.shipped("analyzers")["analyzers"]
    names = [a["name"] for a in cat]
    assert len(names) == len(set(names))
    for a in cat:
        assert a["languages"] and a["binary"] and a["gives"] and a["how"], a["name"]
        assert set(a["gives"]) <= {"defines", "calls", "imports", "returns", "accepts"}
    covered = {lang for a in cat for lang in a["languages"]}
    assert {"python", "typescript", "javascript", "clojure", "go"} <= covered


def test_a_broken_local_catalog_is_a_config_error(tmp_path):
    from gittok.config import ConfigError

    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "analyzers.yaml").write_text("analyzers:\n  - name: x\n")
    with pytest.raises(ConfigError, match="analyzers"):
        overlay.load("analyzers", home=tmp_path)
