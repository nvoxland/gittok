"""Quizzes generated from facts.

Brief side: `annotate` adds one or two question seeds to a quiz-like lead whose window or file
has facts. A seed names a question kind, the answer, real distractors, and the fact ids that
decide the answer. Validator side: `check` recomputes the answer from the facts store for a
card whose interaction has `answer_fact`, and requires the chosen answer to match it.

Kinds: first_call, caller_count, introduced_in, defined_in, calls_which. Only generic fact
rows are used (definitions, calls, touches): no language rules here.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass

from . import factcheck, facts

KINDS = ("first_call", "calls_which", "caller_count", "introduced_in", "defined_in")
SEEDED_STORIES = ("quiz", "this_or_that", "guess_when")
MAX_SEEDS = 2
MAX_DISTRACTORS = 3
MAX_IDS = 12
MIN_SHA = 7

_IDENT = re.compile(r"[\w$]+(?:(?:::|\.)[\w$]+)*")
_HEX = re.compile(rf"\b[0-9a-f]{{{MIN_SHA},40}}\b")
_INT = re.compile(r"\d+")


class QuizReject(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def _rows(conn, repo: str, sql: str, *args) -> list[dict]:
    rid = facts._repo_id(conn, repo)
    return facts._rows(conn, sql, rid, *args) if rid is not None else []


def _ident(choice: str) -> str | None:
    m = _IDENT.search(choice.replace("`", " "))
    return m.group(0) if m else None


def _same(ident: str | None, name: str, symbol: str | None = None) -> bool:
    return bool(ident) and (
        ident == name or (symbol is not None and factcheck.sym_match(ident, symbol))
    )


# ---------- answers: one function per kind, from the store ----------


class _Truth:
    """What the store says for one (repo, kind, subject): the answers and what counts as real."""

    def __init__(self, conn, repo: str, kind: str, subject: str):
        self.conn, self.repo, self.kind, self.subject = conn, repo, kind, subject
        defs = facts.definitions(conn, repo, subject)
        self.symbols = sorted({d["symbol"] for d in defs})
        self.defs = defs
        self.ok = len(self.symbols) == 1
        self.ids: list[str] = []
        self.answers: list[str] = []  # display values of every correct answer
        if self.ok:
            getattr(self, "_" + kind)()

    def _calls(self) -> list[dict]:
        return facts.callees(self.conn, self.repo, self.symbols[0])

    def _first_call(self):
        rows = self._calls()
        if rows:
            self.answers = [rows[0]["callee_name"]]
            self.ids = [r["fact_id"] for r in rows[:2]]
            if len(rows) > 1 and rows[1]["line"] == rows[0]["line"]:
                self.ok = False  # a tie on the first line: no single first call

    def _calls_which(self):
        rows = self._calls()
        self.answers = sorted({r["callee_name"] for r in rows})
        self.ids = [r["fact_id"] for r in rows[:MAX_IDS]]

    def _caller_count(self):
        rows = facts.callers_of(self.conn, self.repo, self.subject, MAX_IDS, resolved_only=True)
        self.answers = [str(facts.count_resolved_callers(self.conn, self.repo, self.subject))]
        self.ids = [d["fact_id"] for d in self.defs] + [r["fact_id"] for r in rows]
        self.ids = self.ids[:MAX_IDS]

    def _introduced_in(self):
        t = facts.history(self.conn, self.repo, self.symbols[0])["introduced"]
        if t:
            self.answers = [t["commit_sha"]]
            self.ids = [t["fact_id"]]

    def _defined_in(self):
        self.answers = sorted({d["path"] for d in self.defs})
        self.ids = [d["fact_id"] for d in self.defs]

    # -- does a choice name a correct answer / a real thing? --

    def correct(self, choice: str) -> bool:
        if self.kind in ("first_call", "calls_which"):
            return any(_same(_ident(choice), a) for a in self.answers)
        if self.kind == "caller_count":
            m = _INT.search(choice)
            return bool(m) and m.group(0) == self.answers[0]
        if self.kind == "introduced_in":
            return any(a.startswith(h) for h in _HEX.findall(choice) for a in self.answers)
        return any(_path(choice) == a for a in self.answers)

    def real(self, choice: str) -> bool:
        c, repo = self.conn, self.repo
        if self.kind in ("first_call", "calls_which"):
            ident = _ident(choice)
            if not ident:
                return False
            return any(
                _same(ident, d["name"], d["symbol"])
                for d in _rows(c, repo, "SELECT name, symbol FROM fact_defines WHERE repo_id = ?")
            )
        if self.kind == "caller_count":
            return bool(_INT.search(choice))
        if self.kind == "introduced_in":
            shas = [
                r["commit_sha"]
                for r in _rows(c, repo, "SELECT commit_sha FROM fact_touched WHERE repo_id = ?")
            ]
            return any(s.startswith(h) for h in _HEX.findall(choice) for s in shas)
        p = _path(choice)
        return bool(_rows(c, repo, "SELECT 1 FROM fact_defines WHERE repo_id = ? AND path = ?", p))


def _path(choice: str) -> str:
    p = choice.replace("`", "").strip()
    return p[2:] if p.startswith("./") else p


# ---------- brief side ----------


def _short(sha: str) -> str:
    return sha[: MIN_SHA + 1]


def _seed(
    kind: str, d: dict, truth: _Truth, question: str, answer: str, distractors: list[str]
) -> dict:
    return {
        "seed": kind,
        "subject": d["symbol"],
        "question": question,
        "answer": answer,
        "distractors": distractors[:MAX_DISTRACTORS],
        "fact_ids": truth.ids[:MAX_IDS],
    }


def _seeds_for(conn, repo: str, d: dict) -> list[dict]:
    """Every seed the store supports for definition `d`, best first."""
    out = []
    sym, name = d["symbol"], d["name"]
    calls = facts.callees(conn, repo, sym)
    names = list(dict.fromkeys(r["callee_name"] for r in calls))
    all_defs = _rows(conn, repo, "SELECT name, symbol, path FROM fact_defines WHERE repo_id = ?")
    if len(names) >= 2:
        t = _Truth(conn, repo, "first_call", sym)
        if t.ok and t.answers:
            ds = [n for n in names if n != t.answers[0]]
            out.append(
                _seed(
                    "first_call", d, t, f"Which function does {name} call first?", t.answers[0], ds
                )
            )
    if names:
        t = _Truth(conn, repo, "calls_which", sym)
        callable_names = {n for n in names}
        pool = list(
            dict.fromkeys(
                x["name"] for x in all_defs if x["name"] not in callable_names and x["name"] != name
            )
        )
        pool.sort(
            key=lambda n: not any(x["name"] == n and x["path"] == d["path"] for x in all_defs)
        )
        if t.ok and len(pool) >= 2:
            out.append(
                _seed("calls_which", d, t, f"Which of these does {name} call?", names[0], pool)
            )
    t = _Truth(conn, repo, "caller_count", sym)
    n = int(t.answers[0]) if t.ok and t.answers else 0
    if n >= 1:
        ds = [str(x) for x in dict.fromkeys([n + 1, max(0, n - 1), n + 2]) if x != n]
        out.append(_seed("caller_count", d, t, f"How many places call {name}?", str(n), ds))
    t = _Truth(conn, repo, "introduced_in", sym)
    if t.ok and t.answers:
        others = list(
            dict.fromkeys(
                r["commit_sha"]
                for r in _rows(
                    conn,
                    repo,
                    "SELECT commit_sha FROM fact_touched WHERE repo_id = ? AND path = ?"
                    " ORDER BY ts",
                    d["path"],
                )
                if r["commit_sha"] != t.answers[0]
            )
        )
        if others:
            out.append(
                _seed(
                    "introduced_in",
                    d,
                    t,
                    f"Which commit first touched {name} (oldest in the analysis window)?",
                    _short(t.answers[0]),
                    [_short(s) for s in others],
                )
            )
    t = _Truth(conn, repo, "defined_in", sym)
    if t.ok and len(t.answers) == 1 and len(facts.definitions(conn, repo, name)) == 1:
        paths = list(dict.fromkeys(x["path"] for x in all_defs if x["path"] != d["path"]))
        if paths:
            out.append(_seed("defined_in", d, t, f"Which file defines {name}?", d["path"], paths))
    return out


def seeds_for_lead(conn, lead, story: str) -> list[dict]:
    """Up to MAX_SEEDS seeds for the definitions in the lead's window (or file)."""
    path = getattr(lead, "path", None)
    if not path or story not in SEEDED_STORIES:
        return []
    repo = lead.repo
    rows = _rows(
        conn, repo,
        "SELECT * FROM fact_defines WHERE repo_id = ? AND path = ?"
        " AND kind IN ('function', 'method', 'class') ORDER BY size DESC, start",
        path,
    )  # fmt: skip
    lines = getattr(lead, "lines", None)
    if lines:
        near = [d for d in rows if d["start"] <= lines[1] and d["end"] >= lines[0]]
        rows = near or rows
    out: list[dict] = []
    kinds: set[str] = set()
    for d in rows[:3]:
        for s in _seeds_for(conn, repo, d):
            if story == "guess_when" and s["seed"] != "introduced_in":
                continue
            if s["seed"] not in kinds and len(out) < MAX_SEEDS:
                kinds.add(s["seed"])
                out.append(s)
    return out


def _seed_lines(seeds: list[dict], story: str) -> str:
    use = (
        "context for the year; do not set answer_fact"
        if story == "guess_when"
        else "set interaction.answer_fact to this seed and these fact ids"
    )
    out = []
    for s in seeds:
        out.append(
            f"\n      seed {s['seed']} on `{s['subject']}`: {s['question']} "
            f"right: {s['answer']}; wrong but real: {', '.join(s['distractors'])}; "
            f"fact_ids: {', '.join(s['fact_ids'])} ({use})"
        )
    return "".join(out)


def annotate(conn, repo: str, pairs: list) -> list:
    """(line, lead) pairs with seeds added to quiz-like leads: the line grows a seed block and the
    lead's dict gains `seeds`. Other pairs pass through."""
    out = []
    for line, lead in pairs:
        story = (
            getattr(lead, "story_type", None)
            if not isinstance(lead, dict)
            else lead.get("story_type")
        )
        seeds = seeds_for_lead(conn, lead, story) if story and not isinstance(lead, dict) else []
        if seeds:
            ref = asdict(lead) if is_dataclass(lead) else dict(lead)
            out.append((line + _seed_lines(seeds, story), {**ref, "seeds": seeds}))
        else:
            out.append((line, lead))
    return out


# ---------- validator side ----------


def check(conn, repos: list[str], interaction: dict) -> None:
    """Raise QuizReject when the chosen answer disagrees with the store."""
    af = interaction["answer_fact"]
    kind, subject = af["seed"], af["subject"]
    for fid in af.get("fact_ids", []):
        if facts.get(conn, fid) is None:
            raise QuizReject("wrong_answer", f"fact id {fid} is not in the facts store")
    truth = None
    for repo in repos:
        t = _Truth(conn, repo, kind, subject)
        if t.defs:
            truth = t
            break
    if truth is None:
        raise QuizReject("wrong_answer", f"no definition named {subject!r} in the facts store")
    if not truth.ok or not truth.answers:
        raise QuizReject(
            "wrong_answer",
            f"the facts store has no single answer for {kind} on {subject!r} "
            "(more than one definition, or no data)",
        )
    choices, idx = interaction["choices"], interaction["answer_index"]
    if not truth.correct(choices[idx]):
        raise QuizReject(
            "wrong_answer",
            f"the facts store says the answer to {kind} on {subject!r} is "
            f"{', '.join(truth.answers)}; choice {choices[idx]!r} does not match",
        )
    for n, other in enumerate(choices):
        if n != idx and truth.correct(other):
            raise QuizReject("ambiguous_answer", f"choice {other!r} is also correct per the facts")
    for n, other in enumerate(choices):
        if n != idx and not truth.real(other):
            what = "number" if kind == "caller_count" else "symbol, file or commit"
            raise QuizReject(
                "distractor_unreal", f"choice {other!r} is not a real {what} in the facts store"
            )
