"""Repo profiles: schema, loader, role_for."""

from pathlib import Path

import pytest
import yaml

from codescroll import config, profiles

VALID = {
    "version": 1,
    "written_at": "2026-11-01T10:00:00Z",
    "head_sha": "abc1234",
    "stack": ["clojure", "ring"],
    "roles": {"src/api": "HTTP route tables", "src": "application code"},
    "ignore": ["resources/**", "*.generated.clj"],
    "detectors": [
        {
            "id": "route-table",
            "tag": "entry_point",
            "verdict_hint": "core",
            "match": {"regex": r"\(defroutes\s+(\S+)", "paths": ["src/**/*.clj"]},
            "window": 25,
            "weight": 2,
            "why": "route table {match} at line {line}",
        }
    ],
}


def det(**over):
    d = {"id": "d1", "tag": "smell", "match": {"regex": "x", "paths": ["src/**"]}, "weight": 1}
    d.update(over)
    return d


def prof(**over):
    return {**VALID, **over}


def m(**over):
    return {"regex": "x", "paths": ["a"], **over}


def test_valid_profile_loads():
    p = profiles.parse(VALID, "demo")
    d = p.detectors[0]
    assert (d.id, d.tag, d.verdict_hint, d.weight, d.window) == (
        "route-table",
        "entry_point",
        "core",
        2,
        25,
    )
    assert d.regex and d.ast_grep is None and d.paths == ("src/**/*.clj",)
    assert p.stack == ("clojure", "ring") and p.version == 1 and p.head_sha == "abc1234"


def test_window_defaults_to_20():
    p = profiles.parse(prof(detectors=[det()]), "demo")
    assert p.detectors[0].window == 20


def test_empty_profile():
    p = profiles.Profile()
    assert p.detectors == () and p.ignore is None and p.roles == {}


@pytest.mark.parametrize(
    "bad,needle",
    [
        ({"colour": "red"}, "colour"),
        ({"detectors": [det(tag="Bad Tag")]}, "d1"),
        ({"detectors": [det(weight=5)]}, "d1"),
        ({"detectors": [det(weight=0.01)]}, "d1"),
        ({"detectors": [det(window=41)]}, "d1"),
        ({"detectors": [det(verdict_hint="meh")]}, "d1"),
        ({"detectors": [det(foo=1)]}, "d1"),
        ({"detectors": [det(match=m(ast_grep="f($A)", language="python"))]}, "d1"),
        ({"detectors": [det(match={"paths": ["a"]})]}, "d1"),
        ({"detectors": [det(match=m(paths=["[bad"]))]}, "d1"),
        ({"detectors": [det(match=m(exclude=["/abs"]))]}, "d1"),
        ({"detectors": [det(match=m(regex="(unclosed"))]}, "d1"),
        ({"detectors": [det(match={"ast_grep": "f($A)", "paths": ["a"]})]}, "d1"),
        ({"detectors": [det(why="oops {nope}")]}, "d1"),
        ({"detectors": [det(), det()]}, "d1"),
        ({"ignore": ["../x"]}, "ignore"),
    ],
)
def test_bad_profiles_are_rejected_with_a_clear_error(bad, needle):
    with pytest.raises(config.ConfigError) as e:
        profiles.parse(prof(**bad), "demo")
    assert needle in str(e.value) and "demo" in str(e.value)


def test_role_for_picks_longest_dir():
    p = profiles.parse(VALID, "demo")
    assert p.role_for("src/api/routes.clj") == "HTTP route tables"
    assert p.role_for("src/db/x.clj") == "application code"
    assert p.role_for("srcx/y.clj") is None
    assert p.role_for("README.md") is None


def test_glob_matching():
    g = profiles.glob_matcher
    assert g("src/**/*.clj")("src/a/b/c.clj") and g("src/**/*.clj")("src/c.clj")
    assert not g("src/**/*.clj")("lib/c.clj")
    assert g("*.lock")("deep/dir/x.lock")
    assert g("resources/**")("resources/a/b.json")
    assert not g("src/*.clj")("src/a/b.clj")


def _root(tmp_path, name="demo", data=VALID):
    (tmp_path / "config" / "profiles").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / f"{name}.yaml").write_text(yaml.safe_dump(data))
    return tmp_path


def test_load_profiles_from_dir_and_missing_is_empty(tmp_path):
    root = _root(tmp_path)
    got = profiles.load_profiles(root)
    assert got["demo"].detectors[0].id == "route-table"
    assert "other" not in got
    assert profiles.load_profiles(tmp_path / "nowhere") == {}


def test_load_profile_error_names_file(tmp_path):
    root = _root(tmp_path, data=prof(colour="x"))
    with pytest.raises(config.ConfigError, match="demo.yaml"):
        profiles.load_profiles(root)


def test_real_repo_profiles_load():
    profiles.load_profiles(Path(__file__).parents[1])


def test_config_exposes_profiles_and_role_for(tmp_path):
    root = _root(tmp_path)
    (root / "config" / "repos.yaml").write_text("repos:\n  demo:\n    path: /x\n")
    cfg = config.load_config(root)
    assert cfg.profile("demo").detectors[0].id == "route-table"
    assert cfg.profile("nope").detectors == ()  # no profile: built-ins only
    assert cfg.role_for("demo", "src/api/a.clj") == "HTTP route tables"
    assert cfg.role_for("nope", "src/api/a.clj") is None
