"""Check the facts a card lists against the facts store.

A card may list fact ids ("call-1a2b3c4d5e6f") or typed facts ({"calls": [caller, callee]}).
Each must hold in the store for one of the card's repos. Symbols may be bare names: a bare
name matches a qualified symbol by its last dotted/scoped part, but the relation is exact.
No language rules live here: the store already holds language-neutral rows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from . import facts

_PARTS = re.compile(r"[^\w$]+")
_SPAN = re.compile(r"^([\w$./:\\-]+?)(?:\(.*\))?$")
MIN_IDENT = 3


class FactFalse(Exception):
    pass


class FactWeak(Exception):
    """A typed fact whose only rows come from a source too weak to back it."""


# Source rank, best first. `macro` and `convention` are reserved: nothing writes them yet, and a
# convention row never backs a claim.
_RANKS = ("analyzer:", "schema:", "macro", "syntax", "convention")
TYPED = ("returns", "accepts", "may_be_nil")


def rank(source: str | None) -> int:
    for i, prefix in enumerate(_RANKS):
        if (source or "syntax").startswith(prefix):
            return i
    return len(_RANKS)


def _strong(source: str | None) -> bool:
    return rank(source) <= 1  # analyzer or schema


@cache
def _claims() -> dict:
    for root in (Path.cwd(), Path(__file__).parents[2]):
        file = root / "config" / "claims.yaml"
        if file.is_file():
            return yaml.safe_load(file.read_text()) or {}
    return {}


@dataclass
class Verified:
    ids: list[str] = field(default_factory=list)
    covered: set[str] = field(default_factory=set)  # names, symbols, and paths the facts mention
    typed: set[str] = field(default_factory=set)  # symbols a typed fact backs
    warnings: list[str] = field(default_factory=list)


def _last(sym: str) -> str:
    parts = [p for p in _PARTS.split(sym) if p]
    return parts[-1] if parts else sym


def sym_match(given: str, stored: str) -> bool:
    """Exact, or `given` is a bare name equal to the last part of the qualified `stored`."""
    return given == stored or (given == _last(given) and given == _last(stored))


def _repo_ids(conn, repos) -> list[int]:
    return [rid for name in repos if (rid := facts._repo_id(conn, name)) is not None]


def _has_build(conn, rid: int) -> bool:
    return (
        conn.execute("SELECT 1 FROM fact_builds WHERE repo_id = ?", (rid,)).fetchone() is not None
    )


def _all(conn, rids, sql: str, *args) -> list[dict]:
    out: list[dict] = []
    for rid in rids:
        out += [r for r in facts._rows(conn, sql, rid, *args) if r.get("source") != "convention"]
    return out


def _touch(v: Verified, row: dict, *names) -> None:
    v.ids.append(row["fact_id"])
    for n in names:
        if n:
            v.covered.add(n)
            v.covered.add(_last(n))


def _by_id(conn, rids, fid: str, v: Verified) -> None:
    row = facts.get(conn, fid)
    if row is None or row["repo_id"] not in rids or row.get("source") == "convention":
        raise FactFalse(f"fact id {fid!r} is not in the facts store for this card's repos")
    if fid.startswith("sch-"):
        v.typed.add(row["symbol"])
        v.typed.add(_last(row["symbol"]))
    _touch(
        v, row, row.get("symbol"), row.get("name"), row.get("path"), row.get("caller_symbol"),
        row.get("callee_name"), row.get("callee_symbol"), row.get("module_text"),
    )  # fmt: skip


def _names(params) -> list[str]:
    return [str(p.get("name", "")) if isinstance(p, dict) else str(p) for p in params]


def _nilable(type_text: str | None) -> bool:
    low = (type_text or "").lower()
    for w in _claims().get("nilable_words") or []:
        w = str(w).lower()
        if re.search(rf"\b{re.escape(w)}\b", low) if w.isalnum() else w in low:
            return True
    return False


def _schema_fact(conn, rids, kind: str, args, v: Verified) -> None:
    """returns / accepts / may_be_nil: matched against fact_schema rows of schema or analyzer
    source. A symbol known only from syntax rows gives FactWeak, an unknown one FactFalse."""
    sym = args[0]
    rows = _all(
        conn,
        rids,
        "SELECT * FROM fact_schema WHERE repo_id = ? AND symbol LIKE ?",
        "%" + _last(sym),
    )
    rows = [r for r in rows if sym_match(sym, r["symbol"]) and _strong(r["source"])]
    if not rows:
        defs = _all(
            conn, rids, "SELECT * FROM fact_defines WHERE repo_id = ? AND name = ?", _last(sym)
        )
        defs = [r for r in defs if sym_match(sym, r["symbol"])]
        if defs:
            best = min((d["source"] for d in defs), key=rank)
            raise FactWeak(
                f"`{sym}` has only {best} facts, and a {kind} fact needs a schema or analyzer "
                "fact. Run an analyzer and submit_facts, or drop the typed claim"
            )
        raise FactFalse(f"no schema or analyzer fact for {sym!r} in the facts store")
    rows.sort(key=lambda r: rank(r["source"]))
    if kind == "returns":
        want = " ".join(str(args[1]).split()).lower()
        hits = [
            r for r in rows
            if r["kind"] == "returns" and " ".join((r["type"] or "").split()).lower() == want
        ]  # fmt: skip
    elif kind == "accepts":
        hits = [
            r for r in rows
            if r["kind"] == "accepts" and _names(json.loads(r["params"] or "[]")) == _names(args[1])
        ]  # fmt: skip
    else:
        hits = [r for r in rows if r["kind"] == "returns" and _nilable(r["type"])]
    if not hits:
        raise FactFalse(f"no {kind} fact for {sym!r} matches in the facts store")
    _touch(v, hits[0], hits[0]["symbol"], sym)
    v.typed.update({hits[0]["symbol"], _last(hits[0]["symbol"]), sym, _last(sym)})


def _typed(conn, rids, fact: dict, v: Verified) -> None:
    ((kind, args),) = fact.items()
    if kind in TYPED:
        return _schema_fact(conn, rids, kind, args, v)
    a, b = args
    if kind == "calls":
        rows = _all(
            conn, rids, "SELECT * FROM fact_calls WHERE repo_id = ? AND callee_name = ?", _last(b)
        )
        hits = [
            r for r in rows
            if sym_match(a, r["caller_symbol"]) and (
                (r["resolved"] and sym_match(b, r["callee_symbol"] or "")) or not r["resolved"]
            )
        ]  # fmt: skip
        hits.sort(key=lambda r: not r["resolved"])
        if not hits:
            raise FactFalse(f"no call of {b!r} from {a!r} in the facts store")
        row = hits[0]
        if not row["resolved"]:
            v.warnings.append(f"calls fact {a} -> {b} matched an unresolved call (by name only)")
        _touch(v, row, row["caller_symbol"], row["callee_name"], row["callee_symbol"], a, b)
    elif kind == "defines":
        rows = _all(conn, rids, "SELECT * FROM fact_defines WHERE repo_id = ? AND path = ?", a)
        hits = [r for r in rows if sym_match(b, r["symbol"]) or b == r["name"]]
        if not hits:
            raise FactFalse(f"{a!r} does not define {b!r} in the facts store")
        _touch(v, hits[0], hits[0]["symbol"], hits[0]["name"], a)
    elif kind == "params":
        rows = _all(
            conn, rids, "SELECT * FROM fact_defines WHERE repo_id = ? AND name = ?", _last(a)
        )
        hits = [r for r in rows if sym_match(a, r["symbol"]) and r["params"] == b]
        if not hits:
            raise FactFalse(f"no definition of {a!r} with {b} parameters in the facts store")
        _touch(v, hits[0], hits[0]["symbol"], hits[0]["name"], hits[0]["path"])
    elif kind == "touched":
        rows = _all(
            conn,
            rids,
            "SELECT * FROM fact_touched WHERE repo_id = ? AND symbol LIKE ?",
            "%" + _last(b),
        )
        hits = [
            r for r in rows
            if len(a) >= 7 and r["commit_sha"].startswith(a) and sym_match(b, r["symbol"])
        ]  # fmt: skip
        if not hits:
            raise FactFalse(f"commit {a!r} did not touch {b!r} in the facts store")
        _touch(v, hits[0], hits[0]["symbol"], hits[0]["path"])
    elif kind == "imports":
        rows = _all(conn, rids, "SELECT * FROM fact_imports WHERE repo_id = ? AND path = ?", a)
        hits = [r for r in rows if b in (r["module_text"], r["resolved_path"])]
        if not hits:
            raise FactFalse(f"{a!r} does not import {b!r} in the facts store")
        _touch(v, hits[0], hits[0]["module_text"], hits[0]["resolved_path"], a)
    else:
        raise FactFalse(f"unknown fact kind {kind!r}")


def verify(conn, repos, listed: list) -> Verified:
    """Check every listed fact. Raises FactFalse naming the first one that does not hold."""
    v = Verified()
    if not listed:
        return v
    rids = _repo_ids(conn, repos) if conn is not None else []
    rids = [rid for rid in rids if _has_build(conn, rid)]
    if not rids:
        raise FactFalse(
            f"fact {listed[0]!r} cannot be checked: no facts are built for {list(repos)}"
        )
    for fact in listed:
        try:
            if isinstance(fact, str):
                _by_id(conn, rids, fact, v)
            else:
                _typed(conn, rids, fact, v)
        except FactFalse as e:
            raise FactFalse(f"{fact!r}: {e}") from None
        except FactWeak as e:
            raise FactWeak(f"{fact!r}: {e}") from None
    v.ids = list(dict.fromkeys(v.ids))
    return v


def unbacked(texts: list[str], covered: set[str], haystack) -> list[str]:
    """Backticked identifiers in `texts` that no fact covers and the cited text lacks.

    `haystack` is a callable returning the cited text; it runs only if something is uncovered."""
    pending: list[tuple[str, str]] = []
    for text in texts:
        for raw in re.findall(r"`([^`\n]+)`", text):
            m = _SPAN.match(raw.strip())
            if not m or len(m.group(1)) < MIN_IDENT:
                continue
            bare = m.group(1)
            if bare in covered or _last(bare) in covered:
                continue
            if any(c.endswith("/" + bare) for c in covered):
                continue
            pending.append((raw.strip(), bare))
    if not pending:
        return []
    cited = haystack()
    out: list[str] = []
    for raw, bare in pending:
        if (bare in cited or raw in cited) and raw not in out:
            continue
        if raw not in out:
            out.append(raw)
    return out


def typed_unbacked(texts: list[str], typed: set[str]) -> list[str]:
    """Backticked symbols that `texts` make a typed claim about but no typed fact backs.

    Phrases come from config/claims.yaml; a phrase must follow the symbol closely."""
    phrases = [
        re.compile(p, re.I)
        for plist in (_claims().get("typed_phrases") or {}).values()
        for p in plist
    ]
    out: list[str] = []
    for text in texts:
        for m in re.finditer(r"`([^`\n]+)`", text):
            sym = _SPAN.match(m.group(1).strip())
            if not sym or len(sym.group(1)) < MIN_IDENT:
                continue
            bare = sym.group(1)
            tail = text[m.end() : m.end() + 40]
            if not any(p.match(tail) for p in phrases):
                continue
            if bare in typed or _last(bare) in typed or bare in out:
                continue
            out.append(bare)
    return out
