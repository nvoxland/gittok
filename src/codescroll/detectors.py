"""Run the detector rules of a repo profile over source files.

Rules are data (see profiles.py). A `regex` rule is matched line by line with the third-party
`regex` module under a time limit per file, so a catastrophic pattern cannot hang analysis:
on a timeout the rule skips that file and logs it. An `ast_grep` rule uses ast-grep-py when it
is installed (optional group `profiles`); without it these rules are skipped with one log line.

`run` takes files with `.path`, `.lang.name` and `.lines` (candidates.SourceFile) and returns
hits shaped like candidates, plus `rule_id` and `weight`. Scoring happens in candidates.py.
"""

from __future__ import annotations

import logging
import posixpath
from functools import cache

import regex

from .profiles import Detector, Profile, glob_matcher

log = logging.getLogger("codescroll.detectors")

REGEX_TIMEOUT_S = 0.2  # per file and rule
MAX_LINE = 1000  # characters; longer lines are not matched by regex rules
AST_LANGUAGE_BY_EXT = {".tsx": "tsx"}  # everything else uses the rule's language name


@cache
def ast_grep_available() -> bool:
    try:
        import ast_grep_py  # noqa: F401
    except ImportError:
        return False
    return True


@cache
def _ast_language_ok(language: str) -> bool:
    """ast-grep panics (a BaseException) on a language it does not know."""
    from ast_grep_py import SgRoot

    try:
        SgRoot("", language)
    except BaseException as e:  # noqa: BLE001
        if isinstance(e, KeyboardInterrupt | SystemExit):
            raise
        return False
    return True


@cache
def ast_grep_languages() -> tuple[str, ...]:
    """Languages from a fixed probe list that ast-grep accepts. Empty without ast-grep-py."""
    if not ast_grep_available():
        return ()
    probe = (
        "python typescript tsx javascript java go rust ruby kotlin c cpp csharp swift php "
        "html css json yaml bash lua scala elixir haskell"
    ).split()
    return tuple(x for x in probe if _ast_language_ok(x))


def _clip(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _window(line: int, total: int, size: int) -> tuple[int, int]:
    """`size` lines around `line`, cut at the file ends. The start is not moved back from the
    end, so hits a few lines apart keep different start lines (the stored key)."""
    start = max(1, line - size // 2)
    return start, min(total, start + size - 1)


def _hit(d: Detector, sf, line: int, text: str, match: str) -> dict:
    start, end = _window(line, len(sf.lines), d.window)
    if d.why:
        why = d.why.format_map({"line": line, "match": _clip(match, 60)})
    else:
        why = f"{d.id} at line {line}: {_clip(text)}"
    return {
        "path": sf.path,
        "start": start,
        "end": end,
        "tag": d.tag,
        "why": why,
        "score": 1.0,
        "rule_id": d.id,
        "weight": d.weight,
    }


def _applies(d: Detector, sf, include, exclude) -> bool:
    if d.language and sf.lang.name != d.language:
        return False
    return any(m(sf.path) for m in include) and not any(m(sf.path) for m in exclude)


def _regex_hits(d: Detector, rx, sf, stats: dict | None = None) -> list[dict]:
    out = []
    try:
        for i, line in enumerate(sf.lines):
            if len(line) > MAX_LINE:
                continue
            m = rx.search(line, timeout=REGEX_TIMEOUT_S)
            if m:
                found = next((g for g in m.groups() if g is not None), m.group(0))
                out.append(_hit(d, sf, i + 1, line.strip(), found))
    except TimeoutError:
        log.warning("rule '%s' timed out on %s; the file is skipped for this rule", d.id, sf.path)
        if stats is not None:
            stats.setdefault("timed_out", []).append({"rule_id": d.id, "path": sf.path})
        return []
    return out


def _ast_hits(d: Detector, sf) -> list[dict]:
    from ast_grep_py import SgRoot

    language = AST_LANGUAGE_BY_EXT.get(posixpath.splitext(sf.path)[1], d.language)
    try:
        nodes = SgRoot("\n".join(sf.lines), language).root().find_all(pattern=d.ast_grep)
    except BaseException as e:  # noqa: BLE001  (ast-grep reports bad patterns as panics)
        if isinstance(e, KeyboardInterrupt | SystemExit):
            raise
        log.warning("rule '%s' failed on %s: %s", d.id, sf.path, e)
        return []
    out = []
    for node in nodes:
        text = node.text()
        line = node.range().start.line + 1
        first = text.splitlines()[0] if text else ""
        out.append(_hit(d, sf, line, sf.lines[line - 1].strip(), first))
    return out


def run(profile: Profile, files, stats: dict | None = None) -> list[dict]:
    """Hits of every detector of `profile` over `files`. Never raises on a bad file or rule.

    `stats`, when given, collects `timed_out`: [{rule_id, path}] for regex timeouts."""
    rules = list(profile.detectors)
    if not rules:
        return []
    ast_ok = ast_grep_available()
    skipped = [d for d in rules if d.ast_grep and not ast_ok]
    if skipped:
        log.info(
            "ast-grep-py is not installed (uv sync --group profiles); "
            "skipping %d ast_grep rule(s): %s",
            len(skipped),
            ", ".join(d.id for d in skipped),
        )
    out: list[dict] = []
    for d in rules:
        if d.ast_grep and not ast_ok:
            continue
        if d.ast_grep and not _ast_language_ok(d.language):
            log.info(
                "rule '%s': ast-grep does not support language '%s'; skipped", d.id, d.language
            )
            continue
        include = [glob_matcher(g) for g in d.paths]
        exclude = [glob_matcher(g) for g in d.exclude]
        rx = regex.compile(d.regex) if d.regex else None
        for sf in files:
            if not _applies(d, sf, include, exclude):
                continue
            try:
                out += _regex_hits(d, rx, sf, stats) if rx else _ast_hits(d, sf)
            except Exception as e:  # noqa: BLE001  (one bad rule or file must not stop the run)
                log.warning("rule '%s' failed on %s: %s; skipped", d.id, sf.path, e)
    return out
