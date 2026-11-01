"""Profile owns the file set: scan, ignore and kinds."""

import re
from pathlib import Path

import pytest

from codescroll import brief, candidates, config, gitq, knowledge, profiles
from codescroll.config import AnalysisSettings, ConfigError
from tests.fixture_repo import build_history_repo


def prof(**data):
    return profiles.parse({"version": 1, **data}, "fixture")


def fs(**data):
    return profiles.fileset_for(prof(**data))


def test_defaults_come_from_scan_defaults_yaml():
    d = config.load_scan_defaults()
    assert {"scan", "ignore", "kinds", "generated_markers", "noise"} <= set(d)
    assert "*.py" in d["scan"]


def test_no_profile_uses_bootstrap_defaults():
    f = profiles.fileset_for(None)
    assert f.reads("src/a.py") and not f.reads("node_modules/x/a.js")
    assert not f.reads("src/a.min.js") and not f.reads(".github/x.py")
    assert not f.reads("notes.sql")  # not a known language: not scanned by default
    assert f.kind("tests/a.py") == "test" and f.is_test("src/a_test.go")
    assert f.kind("cassettes/a.json") == "fixture" and f.kind("docs/a.py") == "docs"
    assert f.kind("src/generated/a.py") == "generated" and f.kind("vendor/a.go") == "vendored"
    assert f.kind("src/a.py") is None
    assert f.is_code_dir("src/billing") and not f.is_code_dir("tests/fixtures")


def test_profile_scan_ignore_kinds_replace_defaults():
    f = fs(
        scan=["db/**/*.sql", "src/**/*.py"],
        ignore=["src/old/**"],
        kinds={"generated": ["src/gen/**"], "test": ["t/**"]},
    )
    assert f.reads("db/migrations/001.sql") and f.reads("src/a.py")
    assert not f.reads("src/old/a.py") and not f.reads("README.md")
    assert f.kind("src/gen/a.py") == "generated" and f.is_test("t/a.py")
    # defaults are gone: node_modules is not ignored, tests/ is not a test dir
    assert f.reads("src/node_modules/a.py") and f.kind("tests/a.py") is None


def test_absent_keys_fall_back_per_key():
    f = fs(ignore=["x/**"])  # scan and kinds absent: bootstrap
    assert f.reads("src/a.py") and not f.reads("x/a.py")
    assert f.reads("node_modules/a.js") and f.kind("tests/a.py") == "test"
    g = fs(scan=["*.sql"], kinds={})  # present and empty: no kinds at all
    assert g.kind("tests/a.py") is None


def test_parse_validates_scan_and_kinds():
    with pytest.raises(ConfigError, match="scan"):
        prof(scan=["../x"])
    with pytest.raises(ConfigError, match="kinds"):
        prof(kinds={"bogus": ["a/**"]})
    with pytest.raises(ConfigError, match="kinds"):
        prof(kinds={"test": ["/abs"]})
    with pytest.raises(ConfigError, match="generated_markers"):
        prof(generated_markers=["("])


def test_generated_markers_default_and_override():
    assert profiles.fileset_for(None).has_generated_marker(["# DO NOT EDIT"])
    f = fs(generated_markers=["^// built by tool"])
    assert f.has_generated_marker(["// built by tool"])
    assert not f.has_generated_marker(["# do not edit"])


FILES = {
    "src/app.py": "def main():\n    return 1\n",
    "db/001_init.sql": "-- HACK: temp\nCREATE TABLE a (id int);\nSELECT * FROM a;\n",
    "src/gen/out.py": "def generated():\n    return 2\n",
    "tests/test_app.py": "def test_x():\n    assert 1\n",
}


@pytest.fixture(scope="module")
def repo_path(tmp_path_factory):
    steps = [("base", FILES, "2026-01-20T10:00:00+00:00")]
    return build_history_repo(tmp_path_factory.mktemp("fs") / "repo", steps).path


def read(repo_path, f=None):
    return candidates._read_files(
        repo_path, "main", AnalysisSettings(), candidates.compiled_languages(), f
    )


def test_read_files_without_profile_is_unchanged(repo_path):
    got = {sf.path: sf for sf in read(repo_path)}
    assert set(got) == {"src/app.py", "tests/test_app.py"}  # gen/ is generated: not mined
    assert got["tests/test_app.py"].is_test


def test_read_files_follows_profile_scan_ignore_and_kinds(repo_path):
    f = fs(scan=["**/*.py", "**/*.sql"], kinds={"generated": ["src/gen/**"]}, ignore=[])
    got = {sf.path: sf for sf in read(repo_path, f)}
    assert set(got) == {"src/app.py", "db/001_init.sql", "tests/test_app.py"}
    assert got["db/001_init.sql"].lang.name == "text"
    assert not got["tests/test_app.py"].is_test  # kinds replaced: no test kind


def test_sql_file_gets_profile_hits_and_no_builtin_hits(repo_path):
    p = prof(
        scan=["**/*.sql"],
        ignore=[],
        detectors=[
            {
                "id": "tables",
                "tag": "schema",
                "weight": 1,
                "match": {"regex": r"CREATE TABLE (\w+)", "paths": ["db/**"]},
            }
        ],
    )
    t0 = gitq.commit_time(repo_path, "main")
    out = candidates.mine(repo_path, "main", t0, {}, AnalysisSettings(), profile=p)
    assert [(c["path"], c.get("rule_id")) for c in out] == [("db/001_init.sql", "tables")]


def test_kind_drives_code_path_and_map_visibility():
    p = prof(kinds={"fixture": ["samples/**"], "docs": ["guide/**"]}, ignore=[".hidden/**"])
    f = profiles.fileset_for(p)
    assert brief.code_path("src/a.py", f) and not brief.code_path("samples/a.py", f)
    assert not brief.code_path("guide/a.py", f) and not brief.code_path(".hidden/a.py", f)
    assert brief.code_path("vendor/a.py", f)  # defaults replaced
    assert brief.code_file("src/a.py", f) and not brief.code_file("guide/a.md", f)
    assert knowledge._visible("src/a", f) and not knowledge._visible("samples", f)
    assert not brief._real_dir("samples", f) and brief._real_dir("vendor", f)


def test_no_hard_coded_path_lists_in_python():
    src = Path(config.__file__).parent
    banned = re.compile(
        r"node_modules|cassette|__snapshots__|third_party|\\\.lock|fixtures\?|site-packages"
        r"|__pycache__|bower_components|\\\.min\\\."
    )
    hits = [
        f"{p.name}:{i}: {line.strip()}"
        for p in sorted(src.glob("*.py"))
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if banned.search(line)
    ]
    assert not hits, "\n".join(hits)
