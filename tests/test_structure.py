"""The tree-sitter structure layer. Tests that need a grammar skip cleanly
when the `structure` group or the grammar bundle is missing."""

import pytest

from codescroll import structure


def need(*grammars):
    ok = structure.available() and all(structure.ready(g) for g in grammars)
    return pytest.mark.skipif(not ok, reason="needs `uv sync --group structure` and its grammars")


def facts(path, text, **kw):
    f = structure.parse(path, text, **kw)
    assert f is not None
    return f


def by_name(f):
    return {d.name: d for d in f.defs}


def test_without_the_pack_parse_returns_none(monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)
    assert structure.parse("a.py", "x = 1\n") is None
    assert structure.grammar_for("a.py") is None


def test_shipped_data_loads():
    spec = structure.spec()
    assert {"python", "clojure", "typescript", "go", "ruby", "java", "rust"} <= set(
        spec["languages"]
    )
    assert structure.language_for("a.go") == "go"
    assert structure.language_for("web/a.svelte") == "typescript"
    assert structure.language_for("a.zig") is None


PY = '''import os
from .x import (y,
                z)


def top(self, a, *args, b=1, **kw):
    """TODO in a docstring"""
    s = "# TODO in a string"
    for i in a:
        if i:  # TODO real comment
            while b:
                return 1


class K:
    def method(self, p):
        pass


def _private():
    pass
'''


@need("python")
def test_python_defs_comments_imports():
    f = facts("a.py", PY)
    d = by_name(f)
    assert d["top"].kind == "function" and d["top"].params == 4  # self is not counted
    assert d["top"].start == 6 and d["top"].end == 12
    assert d["top"].depth == 4 and d["top"].depth_at == 12  # body is level 1
    assert d["top"].public and d["K"].kind == "class" and d["K"].public
    assert not d["_private"].public and not d["method"].public
    assert [c.text for c in f.comments] == ["# TODO real comment"]
    assert f.comments[0].line == 10
    assert [i.line for i in f.imports] == [1, 2]
    assert "from .x import" in f.imports[1].text


TS = """import { a } from "./x";
export async function f(a: number, {b, c}: T, ...r) {
  if (a) { return 1 } else if (b) { return 2 }
  return a ? 1 : 2;
}
export const g = (x: number) => x;
class C { m(a) {} }
const s = "TODO x"; // TODO real
"""


@need("typescript")
def test_typescript_defs():
    f = facts("a.ts", TS)
    d = by_name(f)
    assert d["f"].params == 3  # the destructuring pattern is one parameter
    assert d["f"].public and d["g"].kind == "function" and d["g"].public
    assert not d["C"].public and d["m"].kind == "method"
    assert d["f"].depth == 2  # else-if chains do not add depth
    assert [i.spec for i in f.imports] == ["./x"]
    assert [c.text for c in f.comments] == ["// TODO real"]


@need("tsx")
def test_tsx_reuses_the_typescript_query():
    f = facts("a.tsx", "export function A() { return <div/>; }\n")
    assert [d.name for d in f.defs] == ["A"]


@need("javascript")
def test_javascript_query():
    f = facts("a.js", "export class A { go(x) {} }\nfunction h(a, b) {}\n")
    assert {d.name: d.kind for d in f.defs} == {"A": "class", "go": "method", "h": "function"}


SVELTE = """<h1>hi</h1>
<script lang="ts">
  // TODO shifted
  export function load(a: number) { return a; }
</script>
"""


@need("svelte", "typescript")
def test_svelte_script_is_reparsed_with_shifted_lines():
    f = facts("a.svelte", SVELTE)
    assert [(d.name, d.start) for d in f.defs] == [("load", 4)]
    assert f.comments[0].line == 3


CLJ = """(ns my.app.core
  (:require [my.app.util :as u :refer [helper]]
            [my.app.db :as db]
            my.app.plain))

(defn run [a {:keys [b c]} & more]
  (when a (if b (u/go c) (helper more))))

(s/defn typed :- s/Int "doc" [x :- s/Int y] x)
(defn- hidden [] 1)
(def ^:private secret 1)
(def answer 42)
(defmethod render :foo [x] x)
(defn multi ([a] a) ([a b c] b))
; TODO real
(def s "TODO not a comment")
"""


@need("clojure")
def test_clojure_defs_and_params():
    f = facts("a.clj", CLJ)
    d = by_name(f)
    assert (
        d["run"].kind == "function" and d["run"].params == 3
    )  # a, the destructuring map (one), more; `&` is not counted
    assert d["run"].depth == 3 and d["run"].public
    assert d["typed"].params == 2  # `x :- Schema` is one parameter
    assert d["multi"].params == 3  # the longest arity
    assert not d["hidden"].public and not d["secret"].public
    assert d["answer"].kind == "var" and d["answer"].public
    assert d["render"].kind == "method" and not d["render"].public
    assert [c.text for c in f.comments] == ["; TODO real"]


@need("clojure")
def test_clojure_namespace_requires():
    f = facts("a.clj", CLJ)
    assert f.namespace == "my.app.core"
    req = {r.ns: r for r in f.requires}
    assert req["my.app.util"].alias == "u" and req["my.app.util"].refers == ["helper"]
    assert req["my.app.db"].alias == "db"
    assert req["my.app.plain"].alias is None
    assert "u/go" in {n for n, _ in f.refs}


OTHERS = {
    "a.go": (
        'package main\nimport (\n\t"fmt"\n\tu "a.com/x/util"\n)\n'
        "func Foo(a, b int, c string) int { if a > 1 { return 1 }; return 0 }\n"
        "type T struct{}\nfunc private() {}\n",
        {"Foo": "function", "T": "type", "private": "function"},
        ["fmt", "a.com/x/util"],
    ),
    "a.rb": (
        'require_relative "lib/util"\nrequire "json"\nclass Foo\n  def go(a, b = 1)\n  end\nend\n',
        {"Foo": "class", "go": "method"},
        ["./lib/util", "json"],
    ),
    "A.java": (
        "package a;\nimport com.x.Util;\n"
        "public class A { int go(int a, String b) { return a; } }\n",
        {"A": "class", "go": "method"},
        ["com.x.Util"],
    ),
    "a.rs": (
        "use crate::util::{a, b};\npub fn go(a: i32, b: &str) {}\nstruct S;\n",
        {"go": "function", "S": "class"},
        ["crate::util"],
    ),
}


@pytest.mark.parametrize("path", sorted(OTHERS))
def test_other_languages_defs_and_import_specs(path):
    text, kinds, specs = OTHERS[path]
    grammar = structure.grammar_for(path) or {"a.rb": "ruby", "A.java": "java"}.get(path, "x")
    if not (structure.available() and structure.ready(grammar)):
        pytest.skip("needs the structure group")
    f = facts(path, text)
    assert {d.name: d.kind for d in f.defs} == kinds
    assert [i.spec for i in f.imports] == specs


@need("go")
def test_go_counts_every_named_parameter_and_exports_by_capital():
    d = by_name(facts("a.go", OTHERS["a.go"][0]))
    assert d["Foo"].params == 3 and d["Foo"].public and not d["private"].public


@need("go")
def test_a_profile_query_replaces_the_shipped_one():
    q = "(function_declaration name: (identifier) @name) @definition.function"
    f = facts("a.go", "package m\nfunc A() {}\ntype T struct{}\n", queries={"go": q})
    assert [d.name for d in f.defs] == ["A"]


@need("go")
def test_check_query_accepts_good_and_rejects_bad_queries():
    ok = "(function_declaration name: (identifier) @name) @definition.function"
    assert structure.check_query("go", ok) is None
    assert "query" in structure.check_query("go", "(function_declaration name: (nope) @name)")
    assert "capture" in structure.check_query("go", "(identifier) @bogus")
    assert "definition" in structure.check_query("go", "(identifier) @name")
    assert structure.check_query("not-a-language", ok) is not None


def test_check_query_says_so_without_the_pack(monkeypatch):
    monkeypatch.setattr(structure, "available", lambda: False)
    assert "structure" in structure.check_query("go", "(identifier) @reference")
