"""Shipped Python is a generic engine: it must not name a language, a stack or a manifest.

Everything about a language lives in data (config/*.yaml, config/queries/) or comes from the
agent that reads the repo. Comments and docstrings are not checked; code and string literals are.
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "blamescroll"
WORDS = re.compile(
    r"\b(clojure|clojurescript|python|typescript|javascript|svelte|golang|rust|ruby|java)\b",
    re.I,
)
MARKERS = re.compile(
    r"deps\.edn|project\.clj|package\.json|pyproject|Gemfile|go\.mod|Cargo\.toml"
    r"|\.cljs?\b|\.py[\"']|\.ts[\"']"
)


def _docstring_lines(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                v = body[0].value
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    out.update(range(body[0].lineno, body[0].end_lineno + 1))
    return out


def test_no_language_or_stack_names_in_shipped_python():
    hits = []
    for file in sorted(SRC.glob("*.py")):
        text = file.read_text()
        skip = _docstring_lines(ast.parse(text))
        for n, line in enumerate(text.splitlines(), 1):
            if n in skip or line.lstrip().startswith("#"):
                continue
            code = line.split("  # ")[0]
            if WORDS.search(code) or MARKERS.search(code):
                hits.append(f"{file.name}:{n}: {line.strip()}")
    assert not hits, "language logic in Python:\n" + "\n".join(hits)
