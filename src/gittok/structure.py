"""The structure layer: definitions, references, comments and imports from tree-sitter.

`parse(path, text)` returns `FileFacts` for a file, or None when the layer cannot help (the
optional `structure` dependency group is not installed, the grammar is not in the local
cache, or the file has no query). The caller then falls back to the regex patterns of
config/languages.yaml, and after that to plain text rules.

What the layer reads is DATA, never code:

- config/queries/<grammar>.scm: a tags-style query. Captures: `@definition.<kind>` with
  `@name` (and `@private`), `@reference`, `@comment`, `@import` with `@import.path` (the module
  spec) and `@import.relative` (marks a spec that is relative to the file).
- config/queries/languages.yaml: extensions, the node types that count as nesting and
  branches, how to count parameters, what is public, and the head symbols of a Lisp.
- a repo profile may carry its own query for a grammar (`queries:`); it replaces the shipped
  one for that grammar. `check_query` validates one.

The pack downloads a grammar bundle on first use (needs network). `ready()` only says yes for
grammars that are already in the local cache, so mining never goes to the network;
`gittok structure --prefetch` downloads them.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

try:  # the optional `structure` group
    import tree_sitter as _ts
    import tree_sitter_language_pack as _pack
except ImportError:  # pragma: no cover - exercised by the monkeypatched tests
    _ts = _pack = None

KNOWN_CAPTURES = {
    "name", "private", "reference", "comment", "import", "import.path", "import.relative",
}  # fmt: skip
INSTALL_HINT = "the tree-sitter structure layer is not installed (reinstall gittok)"
_KIND_ORDER = {"function": 0, "method": 0, "class": 1, "interface": 1, "type": 1, "var": 2}
_NESTED_OWNERS = frozenset({"function", "method", "class"})


# ---------- data ----------


@dataclass
class Def:
    name: str
    kind: str  # function, method, class, interface, type, var
    start: int  # 1-based, inclusive
    end: int
    params: int = 0
    depth: int = 0  # nesting level of the deepest line; the function body is level 1
    depth_at: int = 0
    branches: int = 0
    public: bool = False
    top: bool = True  # not inside another function, method or class


@dataclass
class Comment:
    line: int
    end: int
    col: int
    text: str


@dataclass
class Import:
    line: int
    text: str
    spec: str | None = None


@dataclass
class Require:
    ns: str
    alias: str | None = None
    refers: list[str] = field(default_factory=list)
    refer_all: bool = False


@dataclass
class FileFacts:
    lang: str
    grammar: str
    defs: list[Def] = field(default_factory=list)
    refs: list[tuple[str, int]] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    namespace: str | None = None
    requires: list[Require] = field(default_factory=list)
    thresholds: dict = field(default_factory=dict)

    def comment_only_lines(self, lines: list[str]) -> set[int]:
        """1-based lines whose only content is (part of) a comment."""
        out: set[int] = set()
        for c in self.comments:
            if lines[c.line - 1][: c.col].strip() == "":
                out.update(range(c.line, c.end + 1))
        return out


# ---------- config ----------


def _queries_dir() -> Path:
    from . import config

    try:
        d = config.shared_root() / "config" / "queries"
        if d.is_dir():
            return d
    except config.ConfigError:
        pass
    return config.shipped_root() / "config" / "queries"


@cache
def spec() -> dict:
    """config/queries/languages.yaml."""
    data = yaml.safe_load((_queries_dir() / "languages.yaml").read_text()) or {}
    data.setdefault("languages", {})
    return data


@cache
def _by_ext() -> dict[str, tuple[str, str]]:
    """extension -> (language name, grammar)."""
    return {
        ext: (name, grammar)
        for name, raw in spec()["languages"].items()
        for ext, grammar in (raw.get("extensions") or {}).items()
    }


def _ext(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def language_for(path: str) -> str | None:
    """The shipped language (python, clojure, typescript, go, ...) of `path`, by extension."""
    hit = _by_ext().get(_ext(path))
    return hit[0] if hit else None


def extensions(language: str) -> list[str]:
    return list((spec()["languages"].get(language) or {}).get("extensions") or ())


def grammar_for(path: str, queries: dict | None = None) -> str | None:
    """The grammar to parse `path` with, or None when the layer is off or has no grammar.

    A grammar that is not shipped is found by the pack's own extension table, but only when a
    profile query exists for it."""
    if not available():
        return None
    hit = _by_ext().get(_ext(path))
    if hit:
        return hit[1]
    if queries:
        try:
            g = _pack.detect_language_from_path(path)
        except Exception:
            return None
        if g in queries:
            return g
    return None


def grammar_of_path(path: str, queries: dict | None = None) -> str | None:
    """Like `grammar_for`, but without the check that the layer is installed: the grammar a
    file would use. For the prefetch list."""
    hit = _by_ext().get(_ext(path))
    if hit:
        return hit[1]
    g = grammar_of_extension(_ext(path)) if queries else None
    return g if g in (queries or {}) else None


def grammar_of_extension(ext: str) -> str | None:
    """The pack's grammar for a file extension (".php" -> "php"), or None."""
    if not available():
        return None
    try:
        return _pack.detect_language_from_path("x" + ext)
    except Exception:
        return None


def _rules(language: str | None) -> dict:
    raw = spec()["languages"].get(language or "")
    return {**spec()["generic"], **raw} if raw else dict(spec()["generic"])


def _heads(rules: dict) -> dict[str, str]:
    """head symbol -> kind, for a Lisp."""
    return {h: kind for kind, hs in (rules.get("def_heads") or {}).items() for h in hs}


# ---------- the pack ----------


def available() -> bool:
    return _ts is not None and _pack is not None


@cache
def _downloaded() -> frozenset[str]:
    return frozenset(_pack.downloaded_languages()) if available() else frozenset()


def ready(grammar: str) -> bool:
    """True when `grammar` is in the local cache (no download is needed)."""
    return available() and grammar in _downloaded()


def download(grammars) -> int:
    """Fetch grammars into the local cache. Needs network. Returns how many were requested."""
    if not available():
        raise RuntimeError(INSTALL_HINT)
    names = sorted(set(grammars))
    if names:
        _pack.download(names)
    _downloaded.cache_clear()
    return len(names)


def missing(grammars) -> list[str]:
    return sorted(g for g in set(grammars) if not ready(g))


@cache
def _language(grammar: str):
    return _pack.get_language(grammar)


@cache
def _parser(grammar: str):
    return _pack.get_parser(grammar)


def _shipped_query(grammar: str, language: str | None) -> str | None:
    alias = ((spec()["languages"].get(language or "") or {}).get("query_alias")) or {}
    file = _queries_dir() / f"{alias.get(grammar, grammar)}.scm"
    return file.read_text() if file.is_file() else None


def _expand(text: str, rules: dict) -> str:
    if "{{def_heads}}" in text:
        heads = "|".join(re.escape(h) for h in _heads(rules))
        text = text.replace("{{def_heads}}", f"^({heads})$")
    return text


@cache
def _compiled(grammar: str, text: str):
    return _ts.Query(_language(grammar), text)


def check_query(grammar: str, text: str) -> str | None:
    """None when `text` is a usable tags query for `grammar`, else a message that says why."""
    if not available():
        return INSTALL_HINT
    try:
        lang = _language(grammar)
    except Exception as e:
        return f"unknown or unavailable grammar '{grammar}': {e}"
    try:
        q = _ts.Query(lang, _expand(text, _rules(None)))
    except Exception as e:
        return f"bad query for '{grammar}': {e}"
    names = {q.capture_name(i) for i in range(q.capture_count)}
    for n in sorted(names):
        if n.startswith("_") or n in KNOWN_CAPTURES or n.startswith("definition."):
            continue
        return (
            f"unknown capture @{n}; use @definition.<kind> with @name, @reference, @comment, "
            "@import with @import.path, @import.relative or @private"
        )
    has_def = any(n.startswith("definition.") for n in names)
    if "name" in names and not has_def:
        return "@name needs a @definition.<kind> capture on the whole definition"
    if has_def and "name" not in names:
        return "a @definition.<kind> capture needs a @name capture"
    if not (has_def or names & {"reference", "comment", "import"}):
        return "the query captures nothing: add @definition.*, @reference, @comment or @import"
    return None


# ---------- parsing ----------


def _text(src: bytes, n) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", "replace")


def _sym(src: bytes, n) -> str:
    """Text of a Lisp symbol without its metadata: `ns/name`."""
    name = n.child_by_field_name("name")
    ns = n.child_by_field_name("namespace")
    if name is None:
        return _text(src, n)
    return f"{_text(src, ns)}/{_text(src, name)}" if ns is not None else _text(src, name)


def _head(src: bytes, n) -> str | None:
    """Head symbol (name part only) of a list node, or None."""
    for c in n.named_children:
        if c.type == "sym_lit":
            nm = c.child_by_field_name("name")
            return _text(src, nm) if nm is not None else None
        if c.type not in ("comment", "meta_lit"):
            return None
    return None


def parse(path: str, text: str, queries: dict | None = None) -> FileFacts | None:
    """Facts about one file, or None when the layer cannot parse it (see module doc).

    `queries` maps grammar name -> tags query text and wins over the shipped query."""
    grammar = grammar_for(path, queries)
    if grammar is None or not ready(grammar):
        return None
    language = language_for(path) or grammar
    try:
        emb = (spec().get("embedded") or {}).get(grammar)
        if emb:
            return _parse_embedded(language, grammar, emb, text.encode(), queries or {})
        return _analyze(language, grammar, text.encode(), queries or {}, 0)
    except Exception:
        return None


def _query_text(grammar: str, language: str, queries: dict) -> str | None:
    q = queries.get(grammar)
    if q is None:
        q = _shipped_query(grammar, language)
    return _expand(q, _rules(language)) if q else None


def _parse_embedded(language: str, grammar: str, emb: dict, src: bytes, queries: dict):
    """Files whose code sits inside container nodes (data: `embedded` in languages.yaml)."""
    inner = emb["grammar"]
    root = _parser(grammar).parse(src).root_node
    facts = FileFacts(language, grammar, thresholds=dict(_rules(language).get("thresholds") or {}))
    if not ready(inner):
        return None
    for el in root.children:
        if el.type != emb["container"]:
            continue
        raw = next((c for c in el.children if c.type == emb["body"]), None)
        if raw is None:
            continue
        part = _analyze(
            language, inner, src[raw.start_byte : raw.end_byte], queries, raw.start_point[0]
        )
        if part is None:
            return None
        facts.defs += part.defs
        facts.refs += part.refs
        facts.comments += part.comments
        facts.imports += part.imports
    return facts


def embedded_grammars(grammar: str) -> list[str]:
    """Grammars needed besides `grammar` to read its files (data: `embedded`)."""
    emb = (spec().get("embedded") or {}).get(grammar)
    return [emb["grammar"]] if emb else []


def resolve_rules(language: str) -> dict:
    """Import resolution rules of a language (data: `resolve` in languages.yaml)."""
    return dict((spec()["languages"].get(language) or {}).get("resolve") or {})


@cache
def path_translation() -> dict[int, str]:
    """str.translate table that folds path characters (data: `path_normalize`)."""
    return str.maketrans(spec().get("path_normalize") or {})


def _analyze(language, grammar, src: bytes, queries: dict, off: int) -> FileFacts | None:
    qtext = _query_text(grammar, language, queries)
    if qtext is None:
        return None
    rules = _rules(language)
    facts = FileFacts(language, grammar, thresholds=dict(rules.get("thresholds") or {}))
    root = _parser(grammar).parse(src).root_node
    cursor = _ts.QueryCursor(_compiled(grammar, qtext))
    heads = _heads(rules)
    private_heads = set(rules.get("private_heads") or ())
    found: dict[int, tuple[int, str, object, object, bool]] = {}  # name byte -> best def
    seen_imports: set[tuple[int, str | None]] = set()
    for _, caps in cursor.matches(root):
        if "reference" in caps:
            for n in caps["reference"]:
                nm = _sym(src, n) if n.type == "sym_lit" else _text(src, n)
                facts.refs.append((nm, n.start_point[0] + 1 + off))
        if "comment" in caps:
            for n in caps["comment"]:
                body = _text(src, n).rstrip("\r\n")  # a Clojure comment node holds its newline
                line = n.start_point[0] + 1 + off
                facts.comments.append(
                    Comment(line, line + body.count("\n"), n.start_point[1], body)
                )
        dkey = next((k for k in caps if k.startswith("definition.")), None)
        if dkey and "name" in caps:
            node, name_node = caps[dkey][0], caps["name"][0]
            kind = dkey.split(".", 1)[1]
            private = "private" in caps
            if "_head" in caps:
                head = _text(src, caps["_head"][0])
                kind = heads.get(head)
                if kind is None:
                    continue
                private = private or head in private_heads
                sym = name_node.parent
                meta = sym.child_by_field_name("meta") if sym is not None else None
                private = private or (meta is not None and "private" in _text(src, meta))
            prev = found.get(name_node.start_byte)
            if prev is None or _KIND_ORDER.get(kind, 3) < prev[0]:
                found[name_node.start_byte] = (
                    _KIND_ORDER.get(kind, 3),
                    kind,
                    node,
                    name_node,
                    private,
                )
        if "import" in caps:
            n = caps["import"][0]
            sp = None
            if "import.path" in caps:
                sp = _spec(_text(src, caps["import.path"][0]))
                if "import.relative" in caps and not sp.startswith("."):
                    sp = "./" + sp
            line = n.start_point[0] + 1 + off
            if (line, sp) not in seen_imports:
                seen_imports.add((line, sp))
                facts.imports.append(Import(line, _text(src, n), sp))
                if rules.get("lisp") and rules.get("namespace"):
                    _lisp_ns(src, n, facts, rules["namespace"])
    _finish_defs(src, found.values(), rules, facts, off)
    facts.defs.sort(key=lambda d: (d.start, d.end))
    return facts


def _spec(raw: str) -> str:
    raw = raw.strip().strip("\"'`")
    raw = re.split(r"::\{|::\*|\{|\s+as\s+", raw)[0].rstrip(":")
    return raw


# ---------- definitions: params, nesting, branches ----------


def _finish_defs(src, found, rules, facts: FileFacts, off: int) -> None:
    owners = {n.id for _, kind, n, _, _ in found if kind in _NESTED_OWNERS}
    nest = set(rules.get("nesting") or ())
    branch = set(rules.get("branch") or ())
    flat = {tuple(p) for p in rules.get("flat") or ()}
    nest_rx = re.compile(rules["nesting_regex"]) if rules.get("nesting_regex") else None
    branch_rx = re.compile(rules["branch_regex"]) if rules.get("branch_regex") else None
    lisp = bool(rules.get("lisp"))
    nest_heads = set(rules.get("nesting_heads") or ())
    branch_heads = set(rules.get("branch_heads") or ())

    def is_nest(n) -> bool:
        if lisp:
            return n.type == "list_lit" and _head(src, n) in nest_heads
        if n.type in nest or (not nest and nest_rx and nest_rx.match(n.type)):
            p = n.parent
            return not (p is not None and (n.type, p.type) in flat)
        return False

    def is_branch(n) -> bool:
        if lisp:
            return n.type == "list_lit" and _head(src, n) in branch_heads
        return n.type in branch or (not branch and bool(branch_rx and branch_rx.match(n.type)))

    for _, kind, node, name_node, private in found:
        top = True
        p = node.parent
        while p is not None:
            if p.id in owners:
                top = False
                break
            p = p.parent
        d = Def(
            name=_text(src, name_node),
            kind=kind,
            start=node.start_point[0] + 1 + off,
            end=node.end_point[0] + 1 + off,
            top=top,
        )
        d.public = top and not private and kind != "method" and _public(rules, d, node, src)
        if kind in ("function", "method"):
            d.params = _params(src, node, rules)
            d.depth, d.depth_at, d.branches = _shape(node, is_nest, is_branch, off)
        facts.defs.append(d)


def _public(rules: dict, d: Def, node, src: bytes) -> bool:
    pub = rules.get("public") or {}
    if pub.get("private_prefix") and d.name.startswith(pub["private_prefix"]):
        return False
    if pub.get("capitalized") and not d.name[:1].isupper():
        return False
    if pub.get("exported"):
        p = node.parent
        while p is not None and p.type != pub["exported"]:
            p = p.parent
        if p is None:
            return False
    if pub.get("child_type") and not any(c.type == pub["child_type"] for c in node.children):
        return False
    return True


def _params(src: bytes, node, rules: dict) -> int:
    if rules.get("lisp"):
        return _lisp_params(src, node)
    pr = rules.get("params") or {}
    plist = node.child_by_field_name(pr.get("field", "parameters"))
    if plist is None:  # `const f = (a, b) => ...`: the function is the declarator's value
        value = node.child_by_field_name("value")
        plist = value.child_by_field_name(pr.get("field", "parameters")) if value else None
    if plist is None:
        return 0
    ignore = set(pr.get("ignore") or ())
    kids = [c for c in plist.named_children if c.type not in ignore]
    if kids and _text(src, kids[0]) in (pr.get("skip_first") or ()):
        kids = kids[1:]
    multi = pr.get("multi_field")
    if multi:
        return sum(len(c.children_by_field_name(multi)) or 1 for c in kids)
    return len(kids)


def _lisp_params(src: bytes, node) -> int:
    """Top-level forms of the parameter vector (the longest arity). Destructuring forms and
    `x :- Schema` pairs count once; `&` does not count."""

    def count(vec) -> int:
        n, skip = 0, False
        for c in vec.named_children:
            if c.type == "comment":
                continue
            if skip:
                skip = False
                continue
            if c.type == "kwd_lit" and _text(src, c) == ":-":
                skip = True  # the schema form that follows
                continue
            if c.type == "sym_lit" and _text(src, c) == "&":
                continue
            n += 1
        return n

    vecs = [c for c in node.named_children if c.type == "vec_lit"]
    if vecs:
        return count(vecs[0])
    arities = [
        next((x for x in c.named_children if x.type == "vec_lit"), None)
        for c in node.named_children
        if c.type == "list_lit"
    ]
    return max((count(v) for v in arities if v is not None), default=0)


def _shape(node, is_nest, is_branch, off: int) -> tuple[int, int, int]:
    """(depth, line of the deepest node, branch count) inside `node`. Depth is the number of
    enclosing nesting nodes plus one: the function body is level 1."""
    best, at, branches = 0, node.start_point[0] + 1 + off, 0
    stack = [(c, 0) for c in reversed(node.named_children)]
    while stack:
        n, d = stack.pop()
        nested = is_nest(n)
        if is_branch(n):
            branches += 1
        if nested:
            d += 1
        elif d + 1 >= best:
            best, at = d + 1, n.start_point[0] + 1 + off
        stack.extend((c, d) for c in reversed(n.named_children))
    return max(best, 1), at, branches


# ---------- Lisp namespaces ----------


def _lisp_ns(src: bytes, form, facts: FileFacts, keys: dict) -> None:
    kids = [c for c in form.named_children if c.type != "comment"]
    if len(kids) < 2:
        return
    facts.namespace = next(
        (_sym(src, c) for c in kids[1:] if c.type == "sym_lit"),
        None,
    )
    for c in kids[2:]:
        if c.type != "list_lit":
            continue
        items = [x for x in c.named_children if x.type != "comment"]
        if not items or items[0].type != "kwd_lit" or _text(src, items[0]) != keys["require_key"]:
            continue
        for item in items[1:]:
            if item.type == "sym_lit":
                facts.requires.append(Require(_sym(src, item)))
            elif item.type == "vec_lit":
                _require_vec(src, item, facts, keys)


def _require_vec(src: bytes, vec, facts: FileFacts, keys: dict) -> None:
    parts = [x for x in vec.named_children if x.type != "comment"]
    if not parts or parts[0].type != "sym_lit":
        return
    req = Require(_sym(src, parts[0]))
    i = 1
    while i < len(parts):
        key = _text(src, parts[i]) if parts[i].type == "kwd_lit" else None
        val = parts[i + 1] if i + 1 < len(parts) else None
        if key in keys["alias_keys"] and val is not None and val.type == "sym_lit":
            req.alias = _sym(src, val)
        elif key == keys["refer_key"] and val is not None:
            if val.type == "vec_lit":
                req.refers += [_sym(src, x) for x in val.named_children if x.type == "sym_lit"]
            else:
                req.refer_all = _text(src, val) == keys["refer_all"]
        i += 2
    facts.requires.append(req)
