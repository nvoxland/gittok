"""Shipped Python is a generic engine: it must not name a language, a stack or a manifest.

Everything about a language lives in data (config/*.yaml, config/queries/) or comes from the
agent that reads the repo. Comments and docstrings are not checked; code and string literals are.
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "gittok"
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


# Syntax of a language, as it shows in a string constant: comment markers, definition and
# import keywords, receiver names. `LITERALS` are whole strings (also as items of a tuple or a
# set); `SHAPES` are looked for inside every string, which finds them in regex sources.
LITERALS = {
    "//", "/*", "*/", "#!", "#:", "#[", "<!--", ";", ";;", "self", "cls", "this", "crate",
    "super", "import ", "from ", "(ns ", "defn", "let", "fn", "func",
}  # fmt: skip
SHAPES = re.compile(
    r"\bdefn\b|\bdefonce\b|\(ns\b|\bexport\b\\s|\bconst\b[|\\)]|\bcrate\b"
    r"|\bself\|this\b|\bthis\|self\b|\bself\|cls\b"
    r"|#\|//|//\|#|<!--|/\\\*"
)
# str.strip / lstrip of a set of comment characters, such as lstrip("#/; ").
STRIP = re.compile(r"strip\(\s*f?(['\"])(?=[^'\"]*#)(?=[^'\"]*[/;*])[^'\"]*\1\s*\)")
# Strings that are not about source code.
ALLOWED = {"'self'"}  # the Content-Security-Policy keyword
ALLOWED_IN = {("api.py", ";"), ("db.py", ";")}  # an HTTP header and SQL statements


def _strings(tree: ast.AST):
    """(line, text) of each string constant that is not a docstring."""
    doc = _docstring_lines(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.lineno not in doc:
                yield node.lineno, node.value


def test_no_language_syntax_in_shipped_python():
    """Comment markers, definition keywords and import prefixes are data
    (config/languages.yaml, config/queries/languages.yaml, config/file_types.yaml)."""
    hits = []
    for file in sorted(SRC.glob("*.py")):
        text = file.read_text()
        lines = text.splitlines()
        for n, value in _strings(ast.parse(text)):
            if value in ALLOWED or (file.name, value) in ALLOWED_IN:
                continue
            if value in LITERALS or SHAPES.search(value):
                hits.append(f"{file.name}:{n}: {lines[n - 1].strip()}")
        for n, line in enumerate(lines, 1):
            if STRIP.search(line):
                hits.append(f"{file.name}:{n}: {line.strip()}")
    assert not hits, "language syntax in Python:\n" + "\n".join(sorted(set(hits)))
