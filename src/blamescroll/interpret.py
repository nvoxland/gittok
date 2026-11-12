"""Interpretive claims: why and intent statements cite a source.

A card may list `claims`: {text, kind: "interpretive", source}. A source is one of
{commit: sha}, {comment: {path, line}}, {doc: {path, line}}, {pr: url}. This pass checks that
each source exists and supports the claim, and flags a why-sentence in the first explain panel
that no claim and no listed fact backs.

Rules (all data driven; no language logic here):
- commit: the sha resolves on a card repo, and its message (subject + body) supports the text.
  Supported means, after lowercasing and splitting into words (letters and digits only), that
  (a) 4 words in a row from the claim also occur in a row in the message, or (b) the message
  has fewer than 4 words and all of them occur in a row in the claim, or (c) the claim holds a
  quoted span ("...") of at least 2 words that occurs in a row in the message.
- comment / doc: the line exists at the repo ref in a card repo and is a comment line (its
  stripped text starts with a prefix from `comment_prefixes` in config/file_types.yaml for the
  file extension). A `doc` line may also be any line of a file whose extension is in
  `doc_extensions`.
- pr: `<github repo url>/pull/<n>` for a card repo.
- why sentence: a sentence of the first explain panel that has a word from `why_words` is
  backed when a claim shares a 3-word run with it or most of its long words, or when it names
  a backticked identifier that a listed, verified fact covers.

A source that does not exist is always rejected. A source that exists but does not support the
text, or a why-sentence with no backing, is rejected as `claim_unsourced` only when
`settings.agent.require_claim_sources` is on; otherwise it is a warning.
"""

from __future__ import annotations

import posixpath
import re

from blamescroll import config, factcheck, gitq, links

SPAN = 4  # words in a row that tie a claim to a commit message
OVERLAP_SPAN = 3  # words in a row that tie a claim to a why-sentence
OVERLAP_SHARE = 0.6  # or this share of the sentence's long words
LONG_WORD = 4
_WORDS = re.compile(r"[a-z0-9]+")
_QUOTED = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]")
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_BACKTICKED = re.compile(r"`([^`\n]+)`")


def words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def _has_run(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _runs(ws: list[str], n: int):
    return (ws[i : i + n] for i in range(len(ws) - n + 1))


def supports(claim_text: str, message: str) -> bool:
    """True when the commit message supports the claim text (see the module docstring)."""
    claim, msg = words(claim_text), words(message)
    if not msg:
        return False
    if any(_has_run(msg, run) for run in _runs(claim, SPAN)):
        return True
    if len(msg) < SPAN and _has_run(claim, msg):
        return True
    for q in _QUOTED.findall(claim_text):
        qw = words(q)
        if len(qw) >= 2 and _has_run(msg, qw):
            return True
    return False


def overlaps(sentence: str, claim_text: str) -> bool:
    s, c = words(sentence), words(claim_text)
    if any(_has_run(c, run) for run in _runs(s, OVERLAP_SPAN)):
        return True
    long = {w for w in s if len(w) >= LONG_WORD}
    return bool(long) and len(long & set(c)) / len(long) >= OVERLAP_SHARE


def why_sentences(text: str) -> list[tuple[str, str]]:
    """(sentence, why word) for each sentence of `text` that holds a why-word."""
    pats = [
        (w, re.compile(rf"\b{re.escape(w)}\b", re.I))
        for w in config.file_types().get("why_words") or ()
    ]
    out = []
    for sent in _SENTENCES.split(text):
        sent = sent.strip()
        hit = next((w for w, p in pats if p.search(sent)), None)
        if hit:
            out.append((sent, hit))
    return out


def _comment_line(path: str, line: str) -> bool:
    ext = posixpath.splitext(path)[1].lower()
    prefixes = (config.file_types().get("comment_prefixes") or {}).get(ext) or ()
    text = line.strip()
    return any(text.startswith(p) for p in prefixes)


def _doc_file(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in (config.file_types().get("doc_extensions") or ())


def _repo_base(repo) -> str | None:
    if getattr(repo, "url", None):
        return links.normalize_github_url(repo.url)
    try:
        return links.normalize_github_url(gitq.remote_url(repo.path))
    except gitq.GitError:
        return None


def _check_commit(claim: dict, card: dict, gc, reject) -> str | None:
    sha = claim["source"]["commit"]
    last = None
    for name in card["repos"]:
        try:
            full = gc.commit(name, sha)
        except reject as e:
            last = e
            continue
        try:
            msg = gitq.run(gc.repo(name).path, "show", "-s", "--format=%B", full, max_bytes=100_000)
        except gitq.GitError:
            msg = ""
        if supports(claim["text"], msg):
            return None
        return f"claim {claim['text']!r} does not match the message of commit {sha[:7]}"
    raise last


def _check_line(claim: dict, card: dict, gc, reject) -> str | None:
    kind = "comment" if "comment" in claim["source"] else "doc"
    path, n = claim["source"][kind]["path"], claim["source"][kind]["line"]
    path = path.removeprefix("./")
    missing = None
    for name in card["repos"]:
        repo = gc.repo(name)
        try:
            lines = gc.file_lines(name, repo.ref, path)
        except reject as e:
            missing = missing or e
            continue
        if n > len(lines):
            raise reject("claim_source_missing", f"{path} has {len(lines)} lines; no line {n}")
        if _comment_line(path, lines[n - 1]) or (kind == "doc" and _doc_file(path)):
            return None
        return f"{path}:{n} is not a {'comment' if kind == 'comment' else 'comment or doc'} line"
    raise missing


def _check_pr(claim: dict, card: dict, gc, reject) -> str | None:
    url = claim["source"]["pr"].rstrip("/")
    for name in card["repos"]:
        base = _repo_base(gc.repo(name))
        if base and re.fullmatch(re.escape(base) + r"/pull/\d+", url):
            return None
    raise reject("claim_source_missing", f"{url} is not a pull request URL of a card repo")


def _backed_by_facts(card: dict, conn, sentence: str) -> bool:
    if not card.get("facts"):
        return False
    try:
        covered = factcheck.verify(conn, card["repos"], card["facts"]).covered
    except factcheck.FactFalse:
        return False
    for raw in _BACKTICKED.findall(sentence):
        bare = raw.strip().removesuffix("()")
        if (
            bare in covered
            or factcheck.sym_match(bare, bare)
            and any(factcheck.sym_match(bare, c) for c in covered)
        ):
            return True
    return False


def check(card: dict, gc, conn, strict: bool, reject) -> list[str]:
    """Warnings for the card's claims and why-sentences.

    `reject` is an exception class taking (reason, detail). It is raised for a source that
    does not exist, and for any shortfall when `strict`."""
    problems: list[str] = []
    claims = card.get("claims") or []
    for c in claims:
        src = c["source"]
        if "commit" in src:
            bad = _check_commit(c, card, gc, reject)
        elif "pr" in src:
            bad = _check_pr(c, card, gc, reject)
        else:
            bad = _check_line(c, card, gc, reject)
        if bad:
            problems.append(bad)
    first = next(p["text"] for p in card["depth"] if p["kind"] == "explain")
    for sent, word in why_sentences(first):
        if any(overlaps(sent, c["text"]) for c in claims) or _backed_by_facts(card, conn, sent):
            continue
        problems.append(
            f"the sentence {sent[:80]!r} says why ({word!r}) but no claim or fact backs it. "
            "Add a `claims` entry that cites the commit, comment, doc, or PR that says it, "
            "or state only what the code does"
        )
    if problems and strict:
        raise reject("claim_unsourced", problems[0])
    return [f"claim_unsourced: {p}" for p in problems]
