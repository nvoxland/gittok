"""Candidate miners on the structure layer, and their fallbacks."""

import pytest

from gittok import candidates, gitq, profiles, structure
from gittok.config import AnalysisSettings
from tests.fixture_repo import build_history_repo

DATE = "2026-01-01T10:00:00+00:00"


def needs(*grammars):
    ok = structure.available() and all(structure.ready(g) for g in grammars)
    return pytest.mark.skipif(not ok, reason="needs tree-sitter grammars (structure --prefetch)")


def mine(tmp_path, files, profile=None, settings=None):
    r = build_history_repo(tmp_path / "r", [("one", files, DATE)])
    t0 = gitq.commit_time(r.path, "main")
    return candidates.mine(r.path, "main", t0, {}, settings or AnalysisSettings(), profile=profile)


def find(out, tag, path=None):
    return [c for c in out if c["tag"] == tag and (path is None or c["path"] == path)]


def off(monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)


STRING_SMELL = (
    'MSG = "TODO: HACK this is a string"\nDOC = """\nFIXME inside a docstring\n"""\nx = 1\n'
)


@needs("python")
def test_markers_in_strings_are_not_counted(tmp_path):
    files = {"a.py": STRING_SMELL + "# HACK: a real comment\n"}
    out = mine(tmp_path, files)
    hits = find(out, "smell", "a.py")
    assert len(hits) == 1 and "line 6" in hits[0]["why"]


def test_without_the_layer_markers_in_strings_still_come_from_regexes(tmp_path, monkeypatch):
    off(monkeypatch)
    out = mine(tmp_path, {"a.py": "x = 1  # HACK: here\ny = '# HACK: not code'\n"})
    assert len(find(out, "smell", "a.py")) >= 1


GO_UTIL = """package util

// Helper is exported.
func Helper(a, b, c, d, e, f, g int) int {
	if a > 1 {
		return 1
	}
	return 0
}

func internal() {}
"""
GO_USER = (
    'package main\n\nimport "example.com/app/util"\n\n'
    "func main() { util.Helper(1, 2, 3, 4, 5, 6, 7) }\n"
)


@needs("go")
def test_go_gets_definition_and_fan_in_candidates_from_the_structure_layer(tmp_path):
    # The regex entry of go sets no import rules: they come from config/queries.
    assert candidates.compiled_languages()["go"].raw["import_unit"] == "dir"
    files = {"util/util.go": GO_UTIL, "cmd/a/main.go": GO_USER, "cmd/b/main.go": GO_USER}
    out = mine(tmp_path, files)
    core = find(out, "core", "util/util.go")
    assert core and "imported by 2 files" in core[0]["why"]
    api = find(out, "public_api", "util/util.go")
    assert api and "Helper" in api[0]["why"] and "internal" not in api[0]["why"]
    params = find(out, "many_params", "util/util.go")
    assert params and "Helper() takes 7 parameters" in params[0]["why"]


RB_UTIL = "class Util\n  def self.go\n    1\n  end\nend\n"


@needs("ruby")
def test_ruby_gets_fan_in_from_require_relative(tmp_path):
    files = {
        "lib/util.rb": RB_UTIL,
        "a.rb": 'require_relative "lib/util"\nUtil.go\n',
        "b.rb": 'require_relative "lib/util"\nUtil.go\n',
        "c.rb": 'require "json"\n',
    }
    out = mine(tmp_path, files)
    core = find(out, "core", "lib/util.rb")
    assert core and "imported by 2 files" in core[0]["why"]
    assert find(out, "public_api", "lib/util.rb")


CLJ_CORE = "(ns my.core)\n(defn thing [] 1)\n"


@needs("clojure")
def test_clojure_fan_in_resolves_aliases_and_refers(tmp_path):
    files = {
        "src/my/core.clj": CLJ_CORE,
        "src/my/a.clj": "(ns my.a (:require [my.core :as c]))\n(defn go [] (c/thing))\n",
        "src/my/b.clj": "(ns my.b (:require [my.core :refer [thing]]))\n(defn go [] (thing))\n",
        "src/my/c.clj": "(ns my.c (:require [my.core :as c]))\n(defn go [] 1)\n",  # unused
    }
    out = mine(tmp_path, files)
    core = find(out, "core", "src/my/core.clj")
    assert core and "imported by 2 files" in core[0]["why"]


@needs("python")
def test_python_imports_come_from_import_nodes_not_text(tmp_path):
    files = {
        "app/__init__.py": "",
        "app/core.py": "def thing():\n    return 1\n",
        "app/a.py": "from app import core\n",
        "app/b.py": 'from app import core\n"""\nfrom app import core\n"""\n',
        "app/c.py": 'DOC = """\nfrom app import core\n"""\n',  # a string, not an import
    }
    core = find(mine(tmp_path, files), "core", "app/core.py")
    assert core and "imported by 2 files" in core[0]["why"]


@needs("python")
def test_deep_nesting_and_branches_come_from_nodes(tmp_path):
    body = "".join("    " * (i + 1) + f"if x{i}:\n" for i in range(6)) + "    " * 7 + "return 1\n"
    out = mine(tmp_path, {"a.py": f"def f(x0, x1, x2, x3, x4, x5):\n{body}"})
    nest = find(out, "deep_nesting", "a.py")
    assert nest and "nesting depth 7 at line 8" in nest[0]["why"]
    assert find(out, "many_params", "a.py")[0]["why"].startswith("f() takes 6 parameters")


@needs("typescript")
def test_destructuring_and_defaults_count_once(tmp_path):
    out = mine(tmp_path, {"a.ts": "export function f(a, {b, c, d, e, f2}, g = 1) {}\n"})
    assert not find(out, "many_params")


ZIG = (
    "// HACK: nobody knows\nconst x = 1;\n"
    + "".join("  " * (i + 1) + f"if (a{i}) {{\n" for i in range(7))
    + "x = 1;\n"
    + 'const long = "'
    + "a" * 170
    + '";\n'
)


def test_a_file_type_with_no_grammar_gets_text_fallback_candidates(tmp_path):
    prof = profiles.parse({"scan": ["*.zig"]}, "t")
    out = mine(tmp_path, {"a.zig": ZIG}, profile=prof)
    assert find(out, "smell", "a.zig")
    assert find(out, "long_line", "a.zig")
    deep = find(out, "deep_nesting", "a.zig")
    assert deep and "nesting depth 7" in deep[0]["why"]


def test_text_fallback_ignores_data_files(tmp_path):
    prof = profiles.parse({"scan": ["*.json"]}, "t")
    assert mine(tmp_path, {"a.json": '{"a": "HACK: x"}\n' + "# HACK\n"}, profile=prof) == []


@needs("go")
def test_a_profile_query_is_used(tmp_path):
    q = "(function_declaration name: (identifier) @name) @definition.function"
    prof = profiles.parse({"queries": {"go": q}}, "t")
    out = mine(tmp_path, {"util/util.go": GO_UTIL}, profile=prof)
    why = find(out, "public_api", "util/util.go")[0]["why"]
    assert "Helper" in why and "1 public" in why  # `internal` is lower case; no types captured


def test_profile_queries_are_data_validated_by_shape():
    with pytest.raises(Exception, match="queries"):
        profiles.parse({"queries": {"go": 5}}, "t")
    with pytest.raises(Exception, match="queries"):
        profiles.parse({"queries": {"Not A Grammar!": "(x) @reference"}}, "t")
    assert profiles.parse({"queries": {"go": "(identifier) @reference"}}, "t").queries == {
        "go": "(identifier) @reference"
    }


def test_without_the_layer_the_regex_path_runs(tmp_path, monkeypatch):
    off(monkeypatch)
    files = {
        "app/__init__.py": "",
        "app/core.py": "def thing():\n    return 1\n",
        "app/a.py": "from app import core\n",
        "app/b.py": "from app import core\n",
        "x.go": GO_UTIL,
    }
    out = mine(tmp_path, files)
    assert "imported by 2 files" in find(out, "core", "app/core.py")[0]["why"]
    # go has regex patterns too: without its grammar they find the exported function
    api = find(out, "public_api", "x.go")
    assert api and "Helper" in api[0]["why"] and "internal" not in api[0]["why"]
    assert "Helper() takes 7 parameters" in find(out, "many_params", "x.go")[0]["why"]


def test_without_the_layer_go_imports_resolve_to_the_package_directory(tmp_path, monkeypatch):
    off(monkeypatch)
    files = {"util/util.go": GO_UTIL, "cmd/a/main.go": GO_USER, "cmd/b/main.go": GO_USER}
    core = find(mine(tmp_path, files), "core", "util/util.go")
    assert core and "imported by 2 files" in core[0]["why"]
