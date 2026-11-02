"""Check the facts a card lists against the facts store.

A card may list fact ids ("call-1a2b3c4d5e6f") or typed facts ({"calls": [caller, callee]}).
Each must hold in the store for one of the card's repos. Symbols may be bare names: a bare
name matches a qualified symbol by its last dotted/scoped part, but the relation is exact.
No language rules live here: the store already holds language-neutral rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import facts

_PARTS = re.compile(r"[^\w$]+")
_SPAN = re.compile(r"^([\w$./:\\-]+?)(?:\(.*\))?$")
MIN_IDENT = 3


class FactFalse(Exception):
    pass


@dataclass
class Verified:
    ids: list[str] = field(default_factory=list)
    covered: set[str] = field(default_factory=set)  # names, symbols, and paths the facts mention
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
        out += facts._rows(conn, sql, rid, *args)
    return out


def _touch(v: Verified, row: dict, *names) -> None:
    v.ids.append(row["fact_id"])
    for n in names:
        if n:
            v.covered.add(n)
            v.covered.add(_last(n))


def _by_id(conn, rids, fid: str, v: Verified) -> None:
    row = facts.get(conn, fid)
    if row is None or row["repo_id"] not in rids:
        raise FactFalse(f"fact id {fid!r} is not in the facts store for this card's repos")
    _touch(
        v, row, row.get("symbol"), row.get("name"), row.get("path"), row.get("caller_symbol"),
        row.get("callee_name"), row.get("callee_symbol"), row.get("module_text"),
    )  # fmt: skip


def _typed(conn, rids, fact: dict, v: Verified) -> None:
    ((kind, args),) = fact.items()
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
