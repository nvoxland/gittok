"""Leads for the understanding and interactive story types, drawn from rated candidates.

These nine story types need a window of code worth explaining, not a busy file. The miners
(candidates.py) find windows, the scout (scout.py) rates them, and this module maps each
story type to the tags and verdicts that suit it (table in docs/learning.md, section 12).

Strength of a rated lead is `teachable / 5 x fit`, where fit is 1.0 when tag and verdict both
suit the story type and less when only one does. Unrated windows count only when no rated
window fits the type, at `UNRATED_STRENGTH` of the best rated one. The ledger multiplies in
the reader's novelty and the cooldown brakes when it ranks.
"""

from __future__ import annotations

from dataclasses import dataclass

from codescroll import brief, candidates

UNRATED_STRENGTH = 0.1
PER_FILE = 2  # windows of one file kept per story type
FIT_BOTH, FIT_TAG, FIT_VERDICT, FIT_ANY = 1.0, 0.8, 0.7, 0.8
MIN_AUTHOR_SHARE = 0.2  # an author counts as "clear" in a dir at this share of changed lines

CLEVER_TAGS = frozenset(
    {
        "clever",
        "smell",
        "long_line",
        "deep_nesting",
        "catch_all",
        "sleep",
        "magic_number",
        "big_literal",
    }
)
# Tags and verdicts that make an "any window" story type (snippets, quizzes) happier.
PREFER_TAGS = frozenset({"clever", "core", "entry_point", "smell", "god_file"})
PREFER_VERDICTS = frozenset({"clever", "cursed", "bad", "core"})


@dataclass(frozen=True)
class Spec:
    tags: frozenset | None  # None: any tag
    verdicts: frozenset | None  # None: any verdict
    min_teachable: int = 2


SPECS: dict[str, Spec] = {
    "what_it_does": Spec(
        frozenset({"core", "entry_point", "public_api", "stable_core"}),
        frozenset({"core", "good"}),
    ),
    "journey": Spec(frozenset({"entry_point", "core"}), frozenset({"core", "good"})),
    "analogy": Spec(frozenset({"core", "god_file", "entry_point"}), frozenset({"core"})),
    "cursed_clever_line": Spec(CLEVER_TAGS, frozenset({"clever", "cursed", "bad"})),
    "snippet_callouts": Spec(None, None, 4),
    "quiz": Spec(None, None, 4),
    "this_or_that": Spec(None, None, 4),
    "guess_who": Spec(None, None, 3),  # plus: a dir with two clear authors
    "guess_when": Spec(None, None, 3),  # plus: stable_core, or a file with old lines
}


def _fit(spec: Spec, tag: str, verdict: str | None) -> float | None:
    """How well a window suits the story type; None when it does not."""
    if spec.tags is None:
        return FIT_BOTH if tag in PREFER_TAGS or verdict in PREFER_VERDICTS else FIT_ANY
    by_tag = tag in spec.tags
    by_verdict = verdict is not None and spec.verdicts is not None and verdict in spec.verdicts
    if by_tag and by_verdict:
        return FIT_BOTH
    return FIT_TAG if by_tag else FIT_VERDICT if by_verdict else None


def _top(path: str) -> str:
    return path.split("/")[0] if "/" in path else "."


def _multi_author_dirs(sig: dict) -> set[str]:
    by_dir = (sig.get("author_shares") or {}).get("by_dir") or {}
    return {
        d
        for d, authors in by_dir.items()
        if sum(a.get("share", 0) >= MIN_AUTHOR_SHARE for a in authors) >= 2
    }


def _old_paths(sig: dict, t0) -> set[str]:
    return {o["path"] for o in sig.get("oldest_lines") or [] if brief._old(o.get("ts"), t0)}


def _text(c: dict, rated: bool) -> str:
    where = f"({c['path']}:{c['start']})"
    if not rated:
        return f"[unrated] {c['reason']} {where}"
    return (
        f"[{c['verdict']}] {c['reason']} {where}. Scout: '{c['concept']}' - {c['scout_why']} "
        f"(teachable {c['teachable']})"
    )


def _eligible(story_type: str, c: dict, sig: dict, t0, cache: dict) -> float | None:
    """Fit of one window to a story type, folding in the extra rule of guess_who/guess_when."""
    spec = SPECS[story_type]
    if (
        not brief.code_path(c["path"])
        or brief._TEST.search(c["path"])
        or brief._DOC.search(c["path"])
    ):
        return None
    fit = _fit(spec, c["tag"], c.get("verdict"))
    if fit is None:
        return None
    if story_type == "guess_who":
        if "authors" not in cache:
            cache["authors"] = _multi_author_dirs(sig)
        return fit if _top(c["path"]) in cache["authors"] else None
    if story_type == "guess_when":
        if "old" not in cache:
            cache["old"] = _old_paths(sig, t0)
        old, stable = c["path"] in cache["old"], c["tag"] == "stable_core"
        return fit if old and stable else fit * 0.8 if old or stable else None
    return fit


def leads_for(
    conn, repo: str, story_type: str, sig: dict, t0, limit: int
) -> list[tuple[brief.Lead, float]]:
    """(lead, strength) pairs for one story type, best first. Empty when no window fits."""
    spec = SPECS[story_type]
    cache: dict = {}
    rated_rows = candidates.load_rated(conn, repo, spec.min_teachable)
    scored: list[tuple[float, float, dict]] = []
    for r in rated_rows:
        c = {**r, "reason": r["reason"], "scout_why": r["why"]}
        fit = _eligible(story_type, c, sig, t0, cache)
        if fit is not None:
            scored.append((r["teachable"] / 5 * fit, r["score"], c))
    rated = True
    if not scored:  # unrated windows stand in only when nothing rated fits
        rated = False
        seen = {(r["path"], r["start"], r["tag"]) for r in candidates.load_rated(conn, repo, 1)}
        pool = [
            c
            for c in candidates.load_candidates(conn, repo)
            if (c["path"], c["start"], c["tag"]) not in seen
            and (
                spec.tags is None and c["tag"] in PREFER_TAGS or spec.tags and c["tag"] in spec.tags
            )
        ]
        c_pool = [{**c, "reason": c["why"]} for c in pool]
        elig = [(c, _eligible(story_type, c, sig, t0, cache)) for c in c_pool]
        elig = [(c, f) for c, f in elig if f is not None]
        scored = [(UNRATED_STRENGTH * f / (1 + i), c["score"], c) for i, (c, f) in enumerate(elig)]
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]["path"], t[2]["start"]))
    out: list[tuple[brief.Lead, float]] = []
    per_file: dict[str, int] = {}
    taken: set[tuple[str, int]] = set()
    for strength, _, c in scored:
        if (c["path"], c["start"]) in taken or per_file.get(c["path"], 0) >= PER_FILE:
            continue
        taken.add((c["path"], c["start"]))
        per_file[c["path"]] = per_file.get(c["path"], 0) + 1
        ld = brief.Lead(
            story_type,
            repo,
            "path",
            path=c["path"],
            lines=(c["start"], c["end"]),
            text=_text(c, rated),
            key=f"cand:{c['path']}:{c['start']}:{c['tag']}",
        )
        out.append((ld, round(strength, 4)))
        if len(out) >= limit:
            break
    return out


def dirs_with_core(conn, repo: str, depth: int = 2) -> set[str]:
    """Dirs (up to `depth` levels) that hold a core or entry_point candidate: intro prefers them."""
    out: set[str] = set()
    for tag in ("core", "entry_point"):
        for c in candidates.load_candidates(conn, repo, tag):
            segs = c["path"].split("/")[:-1][:depth]
            out.update("/".join(segs[: i + 1]) for i in range(len(segs)))
    return out
