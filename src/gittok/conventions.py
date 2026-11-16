"""Convention vs reality miner: where a name or a type promises one thing and
the code does another. Generic over the call graph; every rule is data in the repo profile:

- `sinks`: {pattern, kind}. A regex on a callee name, a callee symbol or a line of a definition.
- `conventions`: {name_regex, means: effectful|pure}. What a name promises.
- `nil_guards`: regexes that count as a nil check around the result of a call.
- `nil_markers`: plain text in a `returns` type that means the value may be nil.

Effect reach. A definition is effectful when it calls a sink, or calls an effectful definition,
at most MAX_HOPS calls away. The edge of a call is its resolved callee; an unresolved call counts
only when its callee name belongs to exactly one definition of the repo. The sink call counts as
the last hop. Reach is found by a breadth-first walk from the sink-calling definitions up the
call graph, so every path is a shortest one.

Candidates (tags `convention_mismatch` and `nil_contract`) carry the fact ids of their path. With
no profile data the miner finds nothing. Facts must be built for the same head first; the caller
(`signals.analyze`) runs `refresh` right after the facts.
"""

from __future__ import annotations

from collections import deque

from . import candidates, db, facts, gitq
from .config import AnalysisSettings
from .profiles import DEFAULT_WINDOW, Profile, SafeRegex, fileset_for

MAX_HOPS = 6
NIL_GUARD_LINES = 2  # a guard counts on the call line or this many lines below it
CALLABLE = ("function", "method")
MISMATCH, NIL = candidates.FACT_TAGS


def _rx(key: str, patterns, skipped: list, keep=lambda i: True) -> list[SafeRegex]:
    """The profile regexes of `key`, each under a time limit and named `<key>[<index>]`.
    One that times out is skipped from then on; `skipped` gets its name and the reason."""
    return [SafeRegex(f"{key}[{i}]", p, skipped=skipped) for i, p in enumerate(patterns) if keep(i)]


def _hops(n: int) -> str:
    return f"{n} hop" if n == 1 else f"{n} hops"


def _texts(path, head: str, paths: set[str]) -> dict[str, list[str]]:
    blobs = gitq.ls_tree_blobs(path, head)
    data = gitq.read_blobs(path, list({blobs[p] for p in paths if p in blobs}))
    return {
        p: gitq.split_lines(data[blobs[p]].decode("utf-8", errors="replace"))
        for p in paths
        if p in blobs and blobs[p] in data
    }


def _facts_current(conn, rid: int, head: str) -> bool:
    row = conn.execute("SELECT head_sha FROM fact_builds WHERE repo_id = ?", (rid,)).fetchone()
    return bool(row) and row["head_sha"] == head


def _sink_hit(rx_sinks, *texts):
    for t in texts:
        for rx in rx_sinks:
            m = rx.search(t or "")
            if m:
                return m.group(0)
    return None


def mine(
    conn,
    repo: str,
    path,
    head: str,
    profile: Profile | None,
    settings: AnalysisSettings,
    stats: dict | None = None,
) -> list[dict]:
    """Candidates {path, start, end, tag, why, score, fact_ids}. Read-only.

    `stats`, when given, collects `skipped_rules`: [{rule, reason}] for the profile regexes
    that timed out (they are also logged)."""
    if profile is None:
        return []
    skipped = stats.setdefault("skipped_rules", []) if stats is not None else []
    want_effects = bool(profile.sinks)
    want_nil = bool(profile.nil_markers and profile.nil_guards)
    if not (want_effects or want_nil):
        return []
    rid = facts._repo_id(conn, repo)
    if rid is None or not _facts_current(conn, rid, head):
        return []
    fs = fileset_for(profile)
    defs = [
        d
        for d in facts._rows(
            conn,
            'SELECT fact_id, path, symbol, name, start, "end" AS end FROM fact_defines '
            f"WHERE repo_id = ? AND kind IN ({','.join('?' * len(CALLABLE))}) ORDER BY path, start",
            rid,
            *CALLABLE,
        )  # fmt: skip
        if not fs.is_test(d["path"])
    ]
    calls = facts._rows(
        conn,
        "SELECT fact_id, caller_symbol, callee_name, path, line, resolved, callee_symbol "
        "FROM fact_calls WHERE repo_id = ? ORDER BY path, line",
        rid,
    )
    by_symbol = {d["symbol"]: d for d in defs}
    name_count: dict[str, int] = {}
    for d in defs:
        name_count[d["name"]] = name_count.get(d["name"], 0) + 1
    by_name = {d["name"]: d for d in defs if name_count[d["name"]] == 1}
    texts = _texts(path, head, {d["path"] for d in defs} | {c["path"] for c in calls})
    out: list[dict] = []
    if want_effects:
        out += _effects(profile, defs, calls, by_symbol, by_name, texts, skipped)
    if want_nil:
        out += _nil(conn, rid, profile, defs, calls, by_symbol, by_name, texts, fs, skipped)
    return candidates._bound(out, settings.candidates_per_tag)


def _target(call, by_symbol, by_name):
    """The definition a call reaches: its resolved callee, else the one definition of its name."""
    if call["resolved"] and call["callee_symbol"] in by_symbol:
        return by_symbol[call["callee_symbol"]]
    if not call["resolved"]:
        return by_name.get(call["callee_name"])
    return None


def _effects(profile, defs, calls, by_symbol, by_name, texts, skipped) -> list[dict]:
    sinks = _rx("sinks", [s.pattern for s in profile.sinks], skipped)
    direct: dict[str, tuple[str, str | None]] = {}  # symbol -> (sink text, call fact id)
    for c in calls:
        hit = _sink_hit(sinks, c["callee_name"], c["callee_symbol"])
        if hit and c["caller_symbol"] in by_symbol:
            direct.setdefault(c["caller_symbol"], (hit, c["fact_id"]))
    for d in defs:
        if d["symbol"] in direct:
            continue
        lines = texts.get(d["path"]) or []
        first = d["start"] if d["start"] == d["end"] else d["start"] + 1
        for ln in lines[first - 1 : d["end"]]:
            hit = _sink_hit(sinks, ln)
            if hit:
                direct[d["symbol"]] = (hit, None)
                break
    reverse: dict[str, list[tuple[dict, dict]]] = {}  # callee symbol -> (caller def, call)
    for c in calls:
        caller, callee = by_symbol.get(c["caller_symbol"]), _target(c, by_symbol, by_name)
        if caller and callee and caller is not callee:
            reverse.setdefault(callee["symbol"], []).append((caller, c))
    hops = {s: 1 for s in direct}
    step: dict[str, tuple[dict, dict]] = {}  # symbol -> (call, next definition)
    queue = deque(direct)
    while queue:
        sym = queue.popleft()
        if hops[sym] >= MAX_HOPS:
            continue
        for caller, call in reverse.get(sym, ()):
            if caller["symbol"] not in hops:
                hops[caller["symbol"]] = hops[sym] + 1
                step[caller["symbol"]] = (call, by_symbol[sym])
                queue.append(caller["symbol"])

    names = [c.name_regex for c in profile.conventions]
    means = [c.means for c in profile.conventions]
    effectful = _rx("conventions", names, skipped, lambda i: means[i] == "effectful")
    pure = _rx("conventions", names, skipped, lambda i: means[i] == "pure")
    out = []
    for d in defs:
        sym, name = d["symbol"], d["name"]
        claims = any(rx.search(name) for rx in effectful)
        window = (d["start"], min(d["end"], d["start"] + DEFAULT_WINDOW - 1))
        if sym in hops and effectful and not claims:
            ids, via = [d["fact_id"]], []
            cur = sym
            while cur in step:
                call, nxt = step[cur]
                ids += [call["fact_id"], nxt["fact_id"]]
                via.append(nxt["name"])
                cur = nxt["symbol"]
            hit, call_id = direct[cur]
            if call_id:
                ids.append(call_id)
            n = hops[sym]
            route = f" via {', '.join(via)}" if via else ""
            kind = "pure" if any(rx.search(name) for rx in pure) else "unmarked"
            why = (
                f"{name} reaches {hit}{route} ({_hops(n)}) but its name does not say it has "
                f"effects{' (it looks pure)' if kind == 'pure' else ''}"
            )
            score = 1.0 + 0.2 * min(n - 1, 4) + (0.5 if kind == "pure" else 0.0)
            out.append(_cand(d, window, MISMATCH, why, score, ids))
        elif claims and sym not in hops:
            why = (
                f"{name} is named like an effectful function but reaches no sink within "
                f"{MAX_HOPS} calls (claims effects, has none)"
            )
            out.append(_cand(d, window, MISMATCH, why, 1.2, [d["fact_id"]]))
    return out


def _cand(d, window, tag, why, score, ids) -> dict:
    return {
        "path": d["path"],
        "start": window[0],
        "end": window[1],
        "tag": tag,
        "why": why,
        "score": round(score, 4),
        "fact_ids": list(dict.fromkeys(ids)),
    }


def _nil(conn, rid, profile, defs, calls, by_symbol, by_name, texts, fs, skipped) -> list[dict]:
    guards = _rx("nil_guards", profile.nil_guards, skipped)
    risky = [
        s
        for s in facts._rows(
            conn,
            "SELECT fact_id, symbol, type FROM fact_schema WHERE repo_id = ? AND kind = 'returns'",
            rid,
        )
        if any(m in (s["type"] or "") for m in profile.nil_markers)
    ]
    out, seen = [], set()
    is_test: dict[str, bool] = {}
    by_reached: dict[str, list[dict]] = {}  # symbol -> the calls that reach it, in call order
    for c in calls:
        if c["path"] not in is_test:
            is_test[c["path"]] = fs.is_test(c["path"])
        if is_test[c["path"]]:
            continue
        target = _target(c, by_symbol, by_name)
        reached = {c["callee_symbol"], target["symbol"] if target is not None else None}
        for sym in reached - {None}:
            by_reached.setdefault(sym, []).append(c)
    for s in risky:
        for c in by_reached.get(s["symbol"], ()):
            if c["caller_symbol"] == s["symbol"]:
                continue
            lines = texts.get(c["path"])
            if not lines or (c["path"], c["line"]) in seen:
                continue
            near = lines[c["line"] - 1 : c["line"] + NIL_GUARD_LINES]
            if any(g.search(ln) for g in guards for ln in near):
                continue
            seen.add((c["path"], c["line"]))
            name = c["callee_name"]
            why = (
                f"{name} may return nil ({s['type']}) but {c['caller_symbol']} uses the result "
                f"at line {c['line']} with no nil check"
            )
            out.append(
                {
                    "path": c["path"],
                    "start": max(1, c["line"] - 1),
                    "end": min(len(lines), c["line"] + 3),
                    "tag": NIL,
                    "why": why,
                    "score": 1.3,
                    "fact_ids": list(dict.fromkeys([s["fact_id"], c["fact_id"]])),
                }
            )
    return out


def refresh(
    conn,
    repo: str,
    path,
    head: str,
    settings: AnalysisSettings,
    profile: Profile | None,
    stats: dict | None = None,
) -> int:
    """Mine and store the fact-based candidates; rows the miner no longer finds are removed.
    Does nothing while the facts of `head` are missing, so old rows stay until they are built.
    `stats` is passed to `mine`."""
    rid = facts._repo_id(conn, repo)
    if rid is None or not _facts_current(conn, rid, head):
        return 0
    found = mine(conn, repo, path, head, profile, settings, stats)
    hashes = candidates.window_hashes(path, head, found)
    now = db.now_iso()
    with db.immediate(conn):
        for c in found:
            conn.execute(
                "INSERT INTO candidates(repo, path, line_start, line_end, tag, why, score, "
                "head_sha, first_seen_at, last_seen_at, window_hash, fact_ids) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(repo, path, line_start, tag) DO UPDATE SET "
                "line_end=excluded.line_end, why=excluded.why, score=excluded.score, "
                "head_sha=excluded.head_sha, last_seen_at=excluded.last_seen_at, "
                "window_hash=excluded.window_hash, fact_ids=excluded.fact_ids",
                (
                    repo, c["path"], c["start"], c["end"], c["tag"], c["why"], c["score"],
                    head, now, now,
                    hashes.get((c["path"], c["start"], c["end"])),
                    db.dumps(c["fact_ids"]),
                ),
            )  # fmt: skip
        keep = {(c["path"], c["start"], c["tag"]) for c in found}
        for r in conn.execute(
            "SELECT id, path, line_start, tag FROM candidates WHERE repo = ? AND tag IN (?, ?)",
            (repo, *candidates.FACT_TAGS),
        ).fetchall():
            if (r["path"], r["line_start"], r["tag"]) not in keep:
                conn.execute("DELETE FROM candidates WHERE id = ?", (r["id"],))
    return len(found)
