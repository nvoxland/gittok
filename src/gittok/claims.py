"""Claim checks: numbers, dates, shas, names, and paths in card prose must match git.

Only quiz answers and chart numbers were verified before. This pass reads the prose of a
card (hook, learn, explain, callouts, visual text, comments) and checks the tokens that git
can confirm. It only reads: it never writes to a repo. Evidence that is not available makes
a check skip, never reject. `settings.agent.claim_checks` switches the whole pass off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cached_property

from gittok import config, gitq

MIN_COUNT = 13  # smaller numbers are not checked
DATE_SLACK_DAYS = 1  # timezone
MAX_PATHS = 30  # paths whose history is read for dates and counts
MAX_COMMIT_FILES = 10  # files read from one cited commit
HINT = "cite the commit or path that shows it, or remove it"

_NOT_SHOWN = {"kind", "template", "repo", "path", "commit", "from", "tier", "prompt", "excerpt"}
_COUNT_WORDS = (
    r"commits?|lines?|files?|changed|changes|times|callers?|parameters?|arguments?|args|"
    r"authors?|contributors?"
)
_HEDGES = (
    "over",
    "more than",
    "at least",
    "about",
    "around",
    "nearly",
    "almost",
    "roughly",
    "under",
    "fewer than",
    "less than",
    "up to",
    "approximately",
    "~",
    ">",
    "<",
)

_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_URL = re.compile(r"https?://\S+")
_SHA = re.compile(r"(?<![\w-])[0-9a-f]{7,40}(?![\w-])")
_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}  # fmt: skip
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MDY = re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MON})\.?,?\s+(\d{{4}})\b", re.I)
_COUNT = re.compile(
    rf"(?<![\w.,#/$])(?<!line\s)(?<!lines\s)(?<!L)(\d+(?:,\d{{3}})*)(?![\d%]|\.\d|-\d)"
    rf"\s+(?:[A-Za-z-]+\s+){{0,2}}?(?:{_COUNT_WORDS})\b",
    re.I,
)
_LINE_REF = re.compile(r"\blines?\s+(\d+)(?:\s*(?:-|–|to)\s*(\d+))?", re.I)
_PATH_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]*[\w])")
_INT = re.compile(r"\d[\d,]*")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


@dataclass(frozen=True)
class Unverified:
    token: str
    where: str
    why: str

    def detail(self) -> str:
        return f"{self.token!r} in the {self.where} {self.why}. {HINT}"


# ---------------------------------------------------------------------------
# Token extraction (pure)
# ---------------------------------------------------------------------------


def fields(card: dict) -> list[tuple[str, str]]:
    """(where, text) for every prose field of a card."""
    out = [("hook", card["hook"]), ("learn", card.get("learn", ""))]
    out += [("explain", p["text"]) for p in card["depth"] if p["kind"] == "explain"]
    out += _visual_fields(card["visual"], "visual")
    out += [("comment", c["text"]) for c in card.get("comments", [])]
    return [(w, t) for w, t in out if isinstance(t, str) and t.strip()]


def _visual_fields(value, where: str, key: str | None = None) -> list[tuple[str, str]]:
    if key in _NOT_SHOWN:
        return []
    if key == "callouts":
        where = "callout"
    if isinstance(value, str):
        return [(where, value)]
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _visual_fields(v, where, k)]
    if isinstance(value, list):
        return [x for v in value for x in _visual_fields(v, where, key)]
    return []


def _blank(text: str, spans) -> str:
    for a, b in sorted(spans, reverse=True):
        text = text[:a] + " " * (b - a) + text[b:]
    return text


def _mask(text: str, *, code=True, shas=True, dates=True) -> str:
    spans = [m.span() for m in _URL.finditer(text)]
    if code:
        spans += [m.span() for m in _CODE_SPAN.finditer(text)]
    if dates:
        spans += [m.span() for m in _ISO.finditer(text)]
        spans += [m.span() for m in _MDY.finditer(text)] + [m.span() for m in _DMY.finditer(text)]
    if shas:
        spans += [m.span() for m in _SHA.finditer(text) if _looks_like_sha(m.group())]
    return _blank(text, spans)


def _looks_like_sha(tok: str) -> bool:
    if len(tok) == 40:
        return True
    # A word such as "defaced" is hex but has no digit; a big number has no letter.
    return any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok)


def sha_tokens(text: str) -> list[str]:
    plain = _blank(text, [m.span() for m in _URL.finditer(text)])
    return [m.group() for m in _SHA.finditer(plain) if _looks_like_sha(m.group())]


def date_tokens(text: str) -> list[tuple[str, date]]:
    """(token text, date) for ISO and 'Mon D, YYYY' / 'D Mon YYYY' dates, in order."""
    found: list[tuple[int, str, date]] = []
    for m in _ISO.finditer(text):
        found.append((m.start(), m.group(), _date(m.group(1), m.group(2), m.group(3))))
    for m in _MDY.finditer(text):
        d = _date(m.group(3), _MONTHS[m.group(1).lower()], m.group(2))
        found.append((m.start(), m.group(), d))
    for m in _DMY.finditer(text):
        d = _date(m.group(3), _MONTHS[m.group(2).lower()], m.group(1))
        found.append((m.start(), m.group(), d))
    return [(tok, d) for _, tok, d in sorted(found, key=lambda x: x[0]) if d]


def _date(y, m, d) -> date | None:
    try:
        y = int(y)
        return date(y, int(m), int(d)) if 1990 <= y <= 2100 else None
    except ValueError:
        return None


def _hedged(text: str, start: int) -> bool:
    before = text[max(0, start - 16) : start].lower().rstrip()
    return before.endswith(_HEDGES)


def _count_tokens(text: str) -> list[tuple[str, int]]:
    masked = _mask(text)
    out = []
    for m in _COUNT.finditer(masked):
        n = int(m.group(1).replace(",", ""))
        if n >= MIN_COUNT and not _hedged(masked, m.start(1)):
            out.append((m.group(1), n))
    return out


def line_refs(text: str) -> list[tuple[str, int]]:
    """('line 40', 40) and ('lines 36-60', 60): the highest line named, outside code spans."""
    masked = _mask(text)
    out = []
    for m in _LINE_REF.finditer(masked):
        out.append((m.group(), max(int(g) for g in m.groups() if g)))
    return out


def _structured(name: str) -> bool:
    """Looks like an identifier or path, not a plain word, a flag, or an expression."""
    if any(c in name for c in "_-./:") or re.search(r"[a-z][A-Z]", name):
        return not name.startswith("-")
    return False


def name_tokens(text: str) -> list[str]:
    """Backticked spans that look like one identifier or path (3+ chars, no spaces)."""
    out = []
    for m in _CODE_SPAN.finditer(_blank(text, [x.span() for x in _URL.finditer(text)])):
        span = m.group(1).strip()
        if span.endswith("()"):
            span = span[:-2]
        span = span.lstrip("@#'").rstrip(".,;")
        if len(span) < 3 or re.search(r"[\s=(){}\[\]<>\"'|&$*+,!]", span.rstrip("?!")):
            continue
        if span.startswith(":"):
            span = span[1:]
        if "://" in span or not _structured(span) or span.isdigit():
            continue
        out.append(span)
    return out


def _is_path(name: str) -> bool:
    if name.endswith("/"):
        return True
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in config.file_word_extensions()


# ---------------------------------------------------------------------------
# Evidence (reads git, lazily)
# ---------------------------------------------------------------------------


class Evidence:
    """What the card cites, as text, dates, and numbers. Built on first use."""

    def __init__(self, card, gc, *, haystack, signals_for, lead_texts, extra_numbers):
        self.card, self.gc = card, gc
        self._haystack = haystack
        self.signals_for = signals_for
        self.lead_texts = [t for t in (lead_texts or []) if isinstance(t, str)]
        self.extra_numbers = [n for n in extra_numbers if isinstance(n, int)]
        self.all_text = "\n".join(t for _, t in fields(card))

    # -- what the card cites --
    @cached_property
    def commits(self) -> list[tuple[str, str]]:
        out = []
        for repo, c in self._refs("commit"):
            out.append((repo, self.gc.commit(repo, c)))
        return list(dict.fromkeys(out))

    @cached_property
    def paths(self) -> list[tuple[str, str]]:
        return list(dict.fromkeys(self._refs("path")))

    def _refs(self, key: str) -> list[tuple[str, str]]:
        card = self.card
        refs = [card["visual"]] if card["visual"].get("kind") == "code" else []
        refs += [p for p in card["depth"] if p["kind"] in ("code", "code_diff")] + card["sources"]
        return [(r["repo"], r[key]) for r in refs if key in r]

    @cached_property
    def haystack(self) -> str:
        return "\n".join([self._haystack(), *self.lead_texts, self.commit_text])

    # -- git text of the cited commits --
    @cached_property
    def commit_text(self) -> str:
        parts = []
        for repo, full in self.commits:
            parts.append(self._git(repo, "show", "-s", "--format=%B", full))
        return "\n".join(parts)

    @cached_property
    def stat_text(self) -> str:
        parts = []
        for repo, full in self.commits:
            parts.append(self._git(repo, "show", "--stat", "--format=%B", "--no-color", full))
        return "\n".join(parts)

    def _git(self, repo_name: str, *args: str) -> str:
        try:
            return gitq.run(self.gc.repo(repo_name).path, *args, max_bytes=200_000)
        except gitq.GitError:
            return ""

    # -- the tree at the ref --
    def tree(self, repo_name: str) -> set[str]:
        store = self.gc.__dict__.setdefault("_claim_trees", {})
        if repo_name not in store:
            repo = self.gc.repo(repo_name)
            try:
                store[repo_name] = set(gitq.ls_tree_blobs(repo.path, repo.ref))
            except gitq.GitError:
                store[repo_name] = set()
        return store[repo_name]

    def path_exists(self, name: str) -> bool:
        bare = name.rstrip("/")
        for repo in self.card["repos"]:
            tree = self.tree(repo)
            if bare in tree or any(
                p.endswith("/" + bare) or p.startswith(bare + "/") for p in tree
            ):
                return True
        return False

    def sha_exists(self, sha: str) -> bool:
        if any(full.startswith(sha) for _, full in self.commits):
            return True
        for repo_name in self.card["repos"]:
            try:
                gitq.resolve_commit_id(self.gc.repo(repo_name).path, sha)
                return True
            except gitq.GitError as e:
                if "ambiguous" in str(e):
                    return True
        return False

    def grep(self, text: str) -> bool:
        """The literal text occurs somewhere in a card repo at its ref."""
        for repo_name in self.card["repos"]:
            repo = self.gc.repo(repo_name)
            try:
                code, _ = gitq.run_bytes(
                    repo.path, "grep", "-qF", "-e", text, repo.ref, "--", ok_codes=(0, 1)
                )
            except gitq.GitError:
                continue
            if code == 0:
                return True
        return False

    # -- paths in play: cited, plus paths the prose names that exist --
    @cached_property
    def known_paths(self) -> list[tuple[str, str]]:
        found = list(self.paths)
        for repo_name in self.card["repos"]:
            tree = self.tree(repo_name)
            for m in _PATH_TOKEN.finditer(self.all_text):
                p = m.group(1)
                if p in tree or any(t.startswith(p.rstrip("/") + "/") for t in tree):
                    found.append((repo_name, p.rstrip("/")))
        return list(dict.fromkeys(found))[:MAX_PATHS]

    # -- dates --
    @cached_property
    def dates(self) -> set[date] | None:
        """Dates the card may state; None when the evidence is incomplete."""
        out: set[date] = set()
        for text in (*self.lead_texts, self._haystack(), self.commit_text):
            out.update(d for _, d in date_tokens(text))
        paths = list(self.paths)
        for repo, full in self.commits:
            out.update(self._commit_dates(repo, ["-1", full]))
            names = self._git(repo, "show", "--name-only", "--format=", "--no-color", full)
            changed = [n for n in names.splitlines() if n.strip()]
            if len(changed) > MAX_COMMIT_FILES:
                return None
            paths += [(repo, n) for n in changed]
        by_repo: dict[str, list[str]] = {}
        for repo, p in dict.fromkeys(paths):
            by_repo.setdefault(repo, []).append(p)
        for repo, ps in by_repo.items():
            ref = self.gc.repo(repo).ref
            out.update(self._commit_dates(repo, ["-n", "3000", ref, "--", *ps[:MAX_PATHS]]))
        return out

    def _commit_dates(self, repo: str, args: list[str]) -> set[date]:
        out: set[date] = set()
        for line in self._git(repo, "log", "--format=%aI%n%cI", *args).split():
            try:
                stamp = datetime.fromisoformat(line)
            except ValueError:
                continue
            out.add(stamp.date())
            out.add(stamp.astimezone(UTC).date())
        return out

    # -- numbers --
    @cached_property
    def numbers(self) -> set[int]:
        out = set(self.extra_numbers)
        for text in (*self.lead_texts, self.stat_text):
            out.update(int(x.replace(",", "")) for x in _INT.findall(text) if x.strip(","))
        for repo, path in self.known_paths:
            ref = self.gc.repo(repo).ref
            out.add(self._count(repo, "rev-list", "--count", ref, "--", path))
            names = self._git(repo, "log", "-n", "5000", "--format=%an", ref, "--", path)
            out.add(len({n for n in names.splitlines() if n}))
        out.update(self.window_numbers())
        out.update(self._signal_numbers())
        return out

    def _count(self, repo: str, *args: str) -> int:
        text = self._git(repo, *args).strip()
        return int(text) if text.isdigit() else -1

    def window_numbers(self) -> set[int]:
        """Cited window line numbers and lengths, and the length of each cited file."""
        out: set[int] = set()
        card = self.card
        refs = [card["visual"]] if card["visual"].get("kind") == "code" else []
        refs += [p for p in card["depth"] if p["kind"] == "code"]
        for ref in refs:
            a, b = ref["lines"]
            out.update({a, b, b - a + 1})
        for src in card["sources"]:
            if "lines" in src:
                a, b = src["lines"]
                out.update({a, b, b - a + 1})
        out.update(self.file_lengths())
        return out

    @cached_property
    def _lengths(self) -> list[int]:
        card, out = self.card, []
        refs = [card["visual"]] if card["visual"].get("kind") == "code" else []
        refs += [p for p in card["depth"] if p["kind"] == "code"]
        for ref in refs:
            out.append(len(self.gc.file_lines(ref["repo"], ref["commit"], ref["path"])))
        for src in card["sources"]:
            if "path" in src:
                ref = self.gc.repo(src["repo"]).ref
                out.append(len(self.gc.file_lines(src["repo"], ref, src["path"])))
        return out

    def file_lengths(self) -> list[int]:
        return self._lengths

    def line_bound(self) -> int:
        """The highest line number the cited files and diffs can have."""
        bound = max(self._lengths, default=0)
        for m in _HUNK.finditer(self._haystack()):
            bound = max(bound, int(m.group(1)) + int(m.group(2) or 1))
        return bound

    def _signal_numbers(self) -> set[int]:
        out: set[int] = set()
        if not self.signals_for:
            return out
        wanted = {p for _, p in self.known_paths}
        wanted |= {p.rsplit("/", 1)[0] for p in wanted if "/" in p}
        for repo_name in dict.fromkeys(self.card["repos"]):
            sig = self.signals_for(repo_name) or {}
            for group in ("files", "dirs"):
                for rows in ((sig.get("churn") or {}).get(group) or {}).values():
                    for row in rows:
                        if row.get("path") in wanted:
                            out.update(n for n in (row.get("commits"), row.get("lines")) if n)
            for row in sig.get("co_change") or []:
                if row.get("a") in wanted or row.get("b") in wanted:
                    out.add(row.get("count"))
        return {n for n in out if isinstance(n, int)}


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def first_unverified(
    card: dict,
    gc,
    *,
    haystack,
    signals_for=None,
    lead_texts=None,
    extra_numbers=(),
) -> Unverified | None:
    """The first token in the card's prose that git does not back, or None.

    `haystack` is a callable returning the text of everything the card cites (code at its
    commits, diffs, commit patches). `lead_texts` and `signals_for` add evidence when known.
    """
    ev = Evidence(
        card,
        gc,
        haystack=haystack,
        signals_for=signals_for,
        lead_texts=lead_texts,
        extra_numbers=extra_numbers,
    )
    for where, text in fields(card):
        for sha in sha_tokens(text):
            if not ev.sha_exists(sha):
                return Unverified(sha, where, "is not a commit in the repo")
        bad = _bad_date(text, ev)
        if bad:
            return Unverified(bad, where, "does not match the date of any cited commit or file")
        for name in name_tokens(text):
            if not _name_ok(name, ev):
                return Unverified(name, where, "is not in the cited code, diff, or commit")
        for tok, n in _count_tokens(text):
            if n not in ev.numbers:
                return Unverified(tok, where, "does not match any count in the evidence")
        for tok, n in line_refs(text):
            bound = ev.line_bound()
            if bound and n > bound:
                return Unverified(tok, where, f"is past the end of the cited code ({bound} lines)")
    return None


def _bad_date(text: str, ev: Evidence) -> str | None:
    tokens = date_tokens(text)
    if not tokens:
        return None
    known = ev.dates
    if not known:  # incomplete or empty evidence: skip
        return None
    slack = timedelta(days=DATE_SLACK_DAYS)
    for tok, d in tokens:
        if not any(abs(d - k) <= slack for k in known):
            return tok
    return None


def _name_ok(name: str, ev: Evidence) -> bool:
    hay = ev.haystack
    if name in hay:
        return True
    if _is_path(name):
        return ev.path_exists(name)
    segments = [s for s in re.split(r"[./:]", name) if len(s) >= 3]
    if segments and all(s in hay for s in segments):
        return True
    return ev.path_exists(name) or ev.grep(name)
