"""GitHub links for cards: where a code panel, a diff panel, or a source lives on the web."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from blamescroll import gitq
from blamescroll.config import Config

_GITHUB_RE = re.compile(
    r"^(?:https?://|ssh://git@|git@)github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$"
)
_SHA_RE = re.compile(gitq.HEX_ID_PATTERN + "$")
_BRANCH_RE = re.compile(r"^[\w.-]+(/[\w.-]+)*$")
_remote_cache: dict[Path, str | None] = {}


def normalize_github_url(raw: str | None) -> str | None:
    """`https://github.com/org/name` for a github.com remote (ssh or https), else None."""
    m = _GITHUB_RE.match((raw or "").strip())
    return f"https://github.com/{m.group(1)}/{m.group(2)}" if m else None


def repo_url(cfg: Config, name: str) -> str | None:
    """The GitHub web URL of a configured repo: its `url:` setting, else its `origin`."""
    repo = cfg.repos.get(name)
    if repo is None:
        return None
    if repo.url:
        return normalize_github_url(repo.url)
    if repo.path not in _remote_cache:
        try:
            _remote_cache[repo.path] = normalize_github_url(gitq.remote_url(repo.path))
        except gitq.GitError:
            _remote_cache[repo.path] = None
    return _remote_cache[repo.path]


def _blob(base: str, rev: str, path: str, lines=None) -> str:
    url = f"{base}/blob/{rev}/{quote(path)}"
    return f"{url}#L{lines[0]}-L{lines[1]}" if lines else url


def _branch(ref: str) -> str | None:
    """The ref as a GitHub branch name (`origin/master` -> `master`), or None for HEAD and shas."""
    ref = ref.removeprefix("origin/")
    if ref == "HEAD" or _SHA_RE.match(ref) or not _BRANCH_RE.match(ref):
        return None
    return ref


def _cited_commits(card: dict) -> dict[tuple[str, str], str]:
    """The commit the card cites for each (repo, path), from its visual and depth panels."""
    out: dict[tuple[str, str], str] = {}
    for p in [card.get("visual") or {}, *card.get("depth", [])]:
        if p.get("repo") and p.get("path") and p.get("commit"):
            out.setdefault((p["repo"], p["path"]), p["commit"])
    return out


def _claim_url(cfg: Config, card: dict, src: dict) -> str | None:
    """The web URL of an interpretive claim's source, or None when there is no GitHub URL."""
    if "pr" in src:
        return src["pr"]
    base = repo_url(cfg, card["repo"])
    if base is None:
        return None
    if "commit" in src:
        return f"{base}/commit/{src['commit']}"
    ref = src.get("comment") or src.get("doc")
    rev = _branch(cfg.repos[card["repo"]].ref) if card["repo"] in cfg.repos else None
    if not (ref and rev):
        return None
    return f"{base}/blob/{rev}/{quote(ref['path'])}#L{ref['line']}"


def card_links(cfg: Config, card: dict) -> dict | None:
    """`{"repo_url", "panels": [url|None per depth panel], "sources": [{"label", "url"}]}`.

    None when the card's repo has no GitHub URL.
    """
    base = repo_url(cfg, card["repo"])
    if base is None:
        return None
    panels = []
    for d in card.get("depth", []):
        b = repo_url(cfg, d.get("repo", ""))
        if b and d.get("kind") == "code":
            panels.append(_blob(b, d["commit"], d["path"], d.get("lines")))
        elif b and d.get("kind") == "code_diff":
            panels.append(f"{b}/commit/{d['commit']}")
        else:
            panels.append(None)
    cited = _cited_commits(card)
    sources = []
    for s in card.get("sources", []):
        b = repo_url(cfg, s["repo"])
        if "commit" in s:
            sources.append({"label": s["commit"][:7], "url": b and f"{b}/commit/{s['commit']}"})
            continue
        ref = cfg.repos[s["repo"]].ref if s["repo"] in cfg.repos else "HEAD"
        rev = cited.get((s["repo"], s["path"])) or _branch(ref)
        url = b and rev and _blob(b, rev, s["path"], s.get("lines"))
        sources.append({"label": s["path"], "url": url or None})
    claims = [_claim_url(cfg, card, c.get("source") or {}) for c in card.get("claims") or []]
    return {"repo_url": base, "panels": panels, "sources": sources, "claims": claims}
