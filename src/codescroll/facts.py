"""Syntax facts per repo head: definitions, calls, imports and commit touches.

Built from the structure layer (structure.py) over the files the repo's profile reads and mines.
Every row has `source = 'syntax'` and a stable `fact_id` ("def-", "call-", "imp-", "tch-" and 12
hex chars of a sha1 over the row's fields) that a card can cite. A refresh replaces all rows of
one repo; it does nothing while the head is unchanged.

This module holds NO language rules. What is language specific is data:

- config/queries/*.scm: what a definition, a reference and an import look like.
- config/queries/languages.yaml: `module_sep`, `index_names`, `alias_prefixes`, `drop_segments`,
  `import_spec_regex`, `import_unit` and `qualifier_sep` say how an import names a file and how a
  reference is qualified. A language that sets none of them gets the plain rules (a spec is a
  path, a reference is a bare name).
- later, facts that an agent submits (another source value).

What is stored:

- defines: one row per definition. `symbol` is `<path>:<name>`, or `<namespace>/<name>` when the
  query captured a namespace; a definition inside another one is `<outer>::<name>`. Size, params,
  nesting depth and branch count come from structure.py.
- calls: one row per reference, inside a definition, to a name that some definition of the repo
  has (functions, methods, classes). It is a reference, not proof of a call. `resolved` is true
  only when exactly one definition with that name is reachable from the file: the file itself,
  files its imports resolve to, or the file a qualifier names. Else `resolved = 0` and
  `callee_symbol` is NULL.
- imports: one row per import, with the file it resolves to (NULL when it is not in the repo or
  is ambiguous).
- touched: one row per (commit, definition at head) where the commit's diff changed lines of the
  definition. Bounded by the analysis window and `facts_max_commits`. introduced and
  last_changed are the oldest and newest touch seen.
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import time
from dataclasses import dataclass, field

from . import db, gitq, structure
from .config import AnalysisSettings
from .profiles import fileset_for

log = logging.getLogger(__name__)

SOURCE = "syntax"
CALLABLE = frozenset({"function", "method", "class"})
_TABLES = {
    "def": "fact_defines",
    "call": "fact_calls",
    "imp": "fact_imports",
    "tch": "fact_touched",
}
_MAX_RANGE_LINES = 2000


def fact_id(prefix: str, repo: str, *fields) -> str:
    raw = "\x1f".join([prefix, repo, *map(str, fields)])
    return f"{prefix}-{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


# ---------- data: rules from languages.yaml ----------


def _rules(path: str) -> dict:
    spec = structure.spec()["languages"]
    return spec.get(structure.language_for(path) or "") or {}


def _stem(path: str) -> str:
    return posixpath.splitext(path)[0].replace("-", "_")


# ---------- symbols ----------


def symbols(path: str, ff: structure.FileFacts) -> list[str]:
    """The symbol of each definition of `ff.defs`, in the same order."""
    prefix = f"{ff.namespace}/" if ff.namespace else f"{path}:"
    out = []
    for d in ff.defs:
        chain = [d.name]
        if not d.top:
            outer = _outer(ff.defs, d)
            while outer is not None:
                chain.insert(0, outer.name)
                outer = _outer(ff.defs, outer) if not outer.top else None
        out.append(prefix + "::".join(chain))
    return out


def _outer(defs, d):
    best = None
    for o in defs:
        if o is d or o.kind not in ("function", "method", "class", "interface"):
            continue
        if o.start <= d.start and d.end <= o.end and (o.start, o.end) != (d.start, d.end):
            if best is None or (o.end - o.start) < (best.end - best.start):
                best = o
    return best


def _innermost(defs, line: int):
    best = None
    for i, d in enumerate(defs):
        if d.start <= line <= d.end and (
            best is None or d.end - d.start < best[1].end - best[1].start
        ):
            best = (i, d)
    return best


# ---------- import resolution ----------


@dataclass
class _PathIndex:
    exact: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    suffix: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    dirs: dict[tuple[str, str], set[str]] = field(
        default_factory=dict
    )  # (lang, dir suffix) -> dirs
    members: dict[str, list[str]] = field(default_factory=dict)  # dir -> files
    ns: dict[str, str] = field(default_factory=dict)  # namespace -> path

    def add(self, path: str, namespace: str | None) -> None:
        lang = structure.language_for(path) or ""
        if namespace:
            self.ns.setdefault(namespace, path)
        d = posixpath.dirname(path)
        self.members.setdefault(d, []).append(path)
        parts = d.split("/") if d else []
        for i in range(len(parts)):
            self.dirs.setdefault((lang, "/".join(parts[i:]).replace("-", "_")), set()).add(d)
        stem = _stem(path)
        segs = stem.split("/")
        variants = [segs]
        if len(segs) > 1 and segs[-1] in (_rules(path).get("index_names") or ()):
            variants.append(segs[:-1])
        for v in variants:
            self.exact.setdefault((lang, "/".join(v)), set()).add(path)
            for i in range(len(v)):
                self.suffix.setdefault((lang, "/".join(v[i:])), set()).add(path)


def resolve_import(path: str, spec: str, idx: _PathIndex) -> list[str]:
    """Repo files that import `spec` (as written in `path`) names. Empty when none or ambiguous."""
    rules = _rules(path)
    lang = structure.language_for(path) or ""
    spec = spec.strip()
    if not spec:
        return []
    sep = rules.get("module_sep") or "/"
    for pre in rules.get("alias_prefixes") or ():
        if spec.startswith(pre):
            spec = spec[len(pre) :]
            break
    exts = structure.extensions(lang)
    if sep == "/" and posixpath.splitext(spec)[1] in exts:
        spec = posixpath.splitext(spec)[0]
    here = posixpath.dirname(path)
    exact_key = None
    if spec.startswith(("./", "../")):
        exact_key = posixpath.normpath(posixpath.join(here, spec))
    elif sep != "/" and spec.startswith("."):
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec.lstrip(".").replace(sep, "/")
        base = here
        for _ in range(dots - 1):
            base = posixpath.dirname(base)
        exact_key = posixpath.join(base, rest) if rest else None
        if exact_key is None:
            return []
    if exact_key is not None:
        key = exact_key.replace("-", "_")
        hits = idx.exact.get((lang, key)) or set()
        if rules.get("import_unit") == "dir" and not hits:
            return _dir_files(idx, {exact_key}, path)
        return sorted(hits - {path}) if len(hits) == 1 else []
    drop = set(rules.get("drop_segments") or ())
    segs = [s for s in spec.replace("\\", "/").split(sep) if s and s not in drop]
    if sep != "/":
        segs = [x for s in segs for x in s.split("/") if x]
    for i in range(len(segs)):
        key = "/".join(segs[i:]).replace("-", "_")
        if rules.get("import_unit") == "dir":
            found = idx.dirs.get((lang, key)) or set()
            if len(found) == 1:
                return _dir_files(idx, found, path)
            if found:
                return []
            continue
        hits = idx.suffix.get((lang, key)) or set()
        if len(hits) == 1:
            return sorted(hits - {path})
        if hits:
            return []
    return []


def _dir_files(idx: _PathIndex, dirs, path: str) -> list[str]:
    return sorted({f for d in dirs for f in idx.members.get(d, ())} - {path})


def _import_spec(imp: structure.Import, path: str) -> str | None:
    if imp.spec is not None:
        return imp.spec
    rx = _rules(path).get("import_spec_regex")
    if not rx:
        return None
    m = re.search(rx, " ".join(imp.text.split()))
    return next((g for g in (m.groups() if m else ()) if g), None)


# ---------- the build ----------


@dataclass
class _Built:
    defines: list[tuple] = field(default_factory=list)
    calls: list[tuple] = field(default_factory=list)
    imports: list[tuple] = field(default_factory=list)
    touched: list[tuple] = field(default_factory=list)
    cut: list[str] = field(default_factory=list)


def _read_head(path, head, settings: AnalysisSettings, profile):
    fs = fileset_for(profile)
    picked = [
        (p, sha)
        for p, sha, size in gitq.ls_tree_files(path, head)
        if 0 < size <= settings.facts_max_blob_bytes and fs.reads(p) and fs.mined(p)
    ]
    picked.sort()
    cut = len(picked) > settings.facts_max_files
    picked = picked[: settings.facts_max_files]
    blobs = gitq.read_blobs(path, list({sha for _, sha in picked}))
    queries = profile.queries if profile is not None else None
    parsed: dict[str, structure.FileFacts] = {}
    for p, sha in picked:
        data = blobs.get(sha)
        if data is None or b"\0" in data[:8000]:
            continue
        ff = structure.parse(p, data.decode("utf-8", errors="replace"), queries)
        if ff is not None:
            parsed[p] = ff
    return parsed, cut


def _build(repo: str, path, head: str, t0: int, settings: AnalysisSettings, profile) -> _Built:
    out = _Built()
    parsed, cut = _read_head(path, head, settings, profile)
    if cut:
        out.cut.append("files")
    idx = _PathIndex()
    syms: dict[str, list[str]] = {}
    for p, ff in parsed.items():
        idx.add(p, ff.namespace)
        syms[p] = symbols(p, ff)

    # definitions
    by_name: dict[str, list[tuple[str, str]]] = {}  # name -> [(path, symbol)] of callables
    head_symbols: set[tuple[str, str]] = set()
    for p, ff in parsed.items():
        for d, sym in zip(ff.defs, syms[p], strict=True):
            if len(out.defines) >= settings.facts_max_defs:
                out.cut.append("defs")
                break
            out.defines.append(
                (
                    fact_id("def", repo, p, sym, d.kind, d.start, d.end),
                    p,
                    sym,
                    d.name,
                    d.kind,
                    d.start,
                    d.end,
                    d.end - d.start + 1,
                    d.params,
                    d.depth,
                    d.branches,
                    int(d.public),
                )  # fmt: skip
            )
            head_symbols.add((p, sym))
            if d.kind in CALLABLE:
                by_name.setdefault(d.name, []).append((p, sym))

    # imports, then what each file can reach
    reach: dict[str, set[str]] = {}
    ns_alias: dict[str, dict[str, str]] = {}  # path -> alias or namespace -> file
    refers: dict[str, dict[str, str]] = {}  # path -> referred name -> file
    for p, ff in parsed.items():
        files = {p}
        seen: set[tuple[int, str]] = set()
        rows = []
        for req in ff.requires:
            target = idx.ns.get(req.ns) or next(iter(resolve_import(p, req.ns, idx)), None)
            line = ff.imports[0].line if ff.imports else 1
            rows.append((line, req.ns, target))
            if target:
                files.add(target)
                ns_alias.setdefault(p, {})[req.ns] = target
                if req.alias:
                    ns_alias[p][req.alias] = target
                for r in req.refers:
                    refers.setdefault(p, {})[r] = target
        for imp in ff.imports:
            spec = _import_spec(imp, p)
            if spec is None and ff.requires:
                continue
            hit = resolve_import(p, spec, idx) if spec else []
            if hit:
                files.update(hit)
            resolved = (
                (hit[0] if len(hit) == 1 or not hit else posixpath.dirname(hit[0])) if hit else None
            )
            rows.append((imp.line, spec or " ".join(imp.text.split())[:200], resolved))
        for line, text, resolved in rows:
            if (line, text) in seen:
                continue
            seen.add((line, text))
            out.imports.append((fact_id("imp", repo, p, line, text), p, line, text, resolved))
        reach[p] = files

    # calls
    for p, ff in parsed.items():
        qsep = _rules(p).get("qualifier_sep")
        own = {(d.name, d.start) for d in ff.defs}
        import_lines = {i.line for i in ff.imports}
        seen_calls: set[str] = set()
        for ref, line in ff.refs:
            qual, base = None, ref
            if qsep and qsep in ref and not ref.startswith(qsep):
                qual, _, base = ref.partition(qsep)
            if base not in by_name or (base, line) in own or line in import_lines:
                continue
            inner = _innermost(ff.defs, line)
            caller = syms[p][inner[0]] if inner else f"{p}:"
            if qual is not None:
                scope = {ns_alias.get(p, {}).get(qual)} - {None}
            elif base in refers.get(p, {}):
                scope = {refers[p][base]}
            else:
                scope = reach[p]
            cands = [(cp, cs) for cp, cs in by_name[base] if cp in scope]
            one = cands[0][1] if len(cands) == 1 else None
            fid = fact_id("call", repo, caller, ref, p, line)
            if fid in seen_calls:
                continue
            seen_calls.add(fid)
            if len(out.calls) >= settings.facts_max_calls:
                out.cut.append("calls")
                break
            out.calls.append((fid, caller, ref, p, line, int(one is not None), one))

    _touches(out, repo, path, head, t0, settings, profile, head_symbols)
    out.cut = sorted(set(out.cut))
    return out


def _touches(out, repo, path, head, t0, settings, profile, head_symbols) -> None:
    since = t0 - settings.history_window_days * 86400
    wanted = {p for p, _ in head_symbols}
    commits = gitq.log_new_hunks(path, head, since, settings.facts_max_commits, wanted)
    if len(commits) >= settings.facts_max_commits:
        out.cut.append("commits")
    blob_ids = list({f["blob"] for c in commits for f in c["files"].values() if f["ranges"]})
    blobs = gitq.read_blobs(path, blob_ids)
    queries = profile.queries if profile is not None else None
    parsed: dict[tuple[str, str], tuple | None] = {}
    for c in commits:
        for p, f in c["files"].items():
            data = blobs.get(f["blob"])
            if data is None or not f["ranges"] or len(data) > settings.facts_max_blob_bytes:
                continue
            key = (p, f["blob"])
            if key not in parsed:
                ff = structure.parse(p, data.decode("utf-8", errors="replace"), queries)
                parsed[key] = (ff, symbols(p, ff)) if ff is not None else None
            got = parsed[key]
            if got is None:
                continue
            ff, syms = got
            hit: set[str] = set()
            for a, b in f["ranges"]:
                for line in range(a, min(b, a + _MAX_RANGE_LINES) + 1):
                    inner = _innermost(ff.defs, line)
                    if inner:
                        hit.add(syms[inner[0]])
            for sym in sorted(hit):
                if (p, sym) in head_symbols:
                    out.touched.append(
                        (fact_id("tch", repo, c["sha"], sym), c["sha"], c["ts"], sym, p)
                    )


def _query_key(profile) -> str:
    q = sorted((profile.queries or {}).items()) if profile is not None else []
    return hashlib.sha1(repr(q).encode()).hexdigest()[:12]


def refresh(
    conn,
    repo_name: str,
    path,
    head: str,
    t0: int,
    settings: AnalysisSettings,
    profile=None,
    force: bool = False,
) -> dict:
    """Rebuild the syntax facts of `repo_name` at `head`, unless they are already there.

    Returns `{"built": bool, "counts": {...}}`. Never raises for a git or parse failure: facts
    are an extra, and analysis goes on without them."""
    row = conn.execute("SELECT id FROM repos WHERE name = ?", (repo_name,)).fetchone()
    if row is None:
        return {"built": False, "counts": {}}
    repo_id, qkey = row["id"], _query_key(profile)
    cur = conn.execute(
        "SELECT head_sha, query_key, counts FROM fact_builds WHERE repo_id = ?", (repo_id,)
    ).fetchone()
    if cur and not force and cur["head_sha"] == head and cur["query_key"] == qkey:
        return {"built": False, "counts": db.loads(cur["counts"])}
    if not structure.available():
        return {"built": False, "counts": {}, "reason": structure.INSTALL_HINT}
    started = time.monotonic()
    try:
        b = _build(repo_name, path, head, t0, settings, profile)
    except Exception:
        log.exception("syntax facts failed for %s", repo_name)
        return {"built": False, "counts": {}, "reason": "failed"}
    counts = {
        "defines": len(b.defines),
        "calls": len(b.calls),
        "resolved_calls": sum(c[5] for c in b.calls),
        "imports": len(b.imports),
        "touched": len(b.touched),
        "cut": b.cut,
    }
    ms = int((time.monotonic() - started) * 1000)
    with db.immediate(conn):
        for table in _TABLES.values():
            conn.execute(f"DELETE FROM {table} WHERE repo_id = ?", (repo_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO fact_defines(fact_id, repo_id, path, symbol, name, kind, start,"
            ' "end", size, params, depth, branches, public) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(r[0], repo_id, *r[1:]) for r in b.defines],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path,"
            " line, resolved, callee_symbol) VALUES (?,?,?,?,?,?,?,?)",
            [(r[0], repo_id, *r[1:]) for r in b.calls],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO fact_imports(fact_id, repo_id, path, line, module_text,"
            " resolved_path) VALUES (?,?,?,?,?,?)",
            [(r[0], repo_id, *r[1:]) for r in b.imports],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO fact_touched(fact_id, repo_id, commit_sha, ts, symbol, path)"
            " VALUES (?,?,?,?,?,?)",
            [(r[0], repo_id, *r[1:]) for r in b.touched],
        )
        conn.execute(
            "INSERT OR REPLACE INTO fact_builds(repo_id, head_sha, built_at, duration_ms, counts,"
            " query_key) VALUES (?,?,?,?,?,?)",
            (repo_id, head, db.now_iso(), ms, db.dumps(counts), qkey),
        )
    return {"built": True, "counts": counts, "duration_ms": ms}


# ---------- reading ----------


def _repo_id(conn, repo: str) -> int | None:
    row = conn.execute("SELECT id FROM repos WHERE name = ?", (repo,)).fetchone()
    return row["id"] if row else None


def _rows(conn, sql: str, *args) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def definitions(conn, repo: str, name: str) -> list[dict]:
    """Definitions called `name` (the bare name or the full symbol)."""
    rid = _repo_id(conn, repo)
    return _rows(
        conn,
        "SELECT * FROM fact_defines WHERE repo_id = ? AND (name = ? OR symbol = ?)"
        " ORDER BY path, start",
        rid, name, name,
    )  # fmt: skip


def callers(conn, repo: str, symbol: str) -> list[dict]:
    """Calls that resolved to `symbol`."""
    return _rows(
        conn,
        "SELECT * FROM fact_calls WHERE repo_id = ? AND callee_symbol = ? ORDER BY path, line",
        _repo_id(conn, repo), symbol,
    )  # fmt: skip


def callees(conn, repo: str, symbol: str) -> list[dict]:
    """Calls made inside `symbol`, resolved or not."""
    return _rows(
        conn,
        "SELECT * FROM fact_calls WHERE repo_id = ? AND caller_symbol = ? ORDER BY line",
        _repo_id(conn, repo), symbol,
    )  # fmt: skip


def imports(conn, repo: str, path: str) -> list[dict]:
    return _rows(
        conn,
        "SELECT * FROM fact_imports WHERE repo_id = ? AND path = ? ORDER BY line",
        _repo_id(conn, repo), path,
    )  # fmt: skip


def history(conn, repo: str, symbol: str) -> dict:
    """Touches of `symbol`, newest first, with `introduced` (oldest) and `last_changed` (newest).
    Both are None when no commit of the bounded window touched it."""
    touches = _rows(
        conn,
        "SELECT * FROM fact_touched WHERE repo_id = ? AND symbol = ? ORDER BY ts DESC, commit_sha",
        _repo_id(conn, repo), symbol,
    )  # fmt: skip
    return {
        "symbol": symbol,
        "touches": touches,
        "last_changed": touches[0] if touches else None,
        "introduced": touches[-1] if touches else None,
    }


def facts_in(conn, repo: str, path: str, start: int, end: int | None = None) -> list[dict]:
    """Definitions overlapping, and calls and imports inside, lines `start`..`end` of `path`."""
    end = start if end is None else end
    rid = _repo_id(conn, repo)
    out = _rows(
        conn,
        'SELECT * FROM fact_defines WHERE repo_id = ? AND path = ? AND start <= ? AND "end" >= ?'
        " ORDER BY start",
        rid, path, end, start,
    )  # fmt: skip
    for table in ("fact_calls", "fact_imports"):
        out += _rows(
            conn,
            f"SELECT * FROM {table} WHERE repo_id = ? AND path = ? AND line BETWEEN ? AND ?"
            " ORDER BY line",
            rid, path, start, end,
        )  # fmt: skip
    return out


def get(conn, fact_id_: str) -> dict | None:
    table = _TABLES.get(fact_id_.split("-", 1)[0])
    if table is None:
        return None
    rows = _rows(conn, f"SELECT * FROM {table} WHERE fact_id = ?", fact_id_)
    return rows[0] if rows else None
