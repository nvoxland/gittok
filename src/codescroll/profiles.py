"""Repo profiles: per-repo detector rules kept as data.

A profile lives in `config/profiles/<repo>.yaml` inside CodeScroll, never in the user's repo.
It holds the stack, a role per directory, detector rules, and ignore globs. Rules are data:
a regex or an ast-grep pattern plus path globs. CodeScroll never runs code from a profile.
The engine that applies the rules is in `candidates.py`; the format is in
`schema/profile.schema.json`. No profile file means built-in detectors only.

Glob syntax: `*` matches inside one path part, `**` matches across parts, `?` matches one
character, `[abc]` is a class. A glob with no `/` matches the file name at any depth.
"""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from pathlib import Path

import regex
import yaml
from jsonschema import Draft202012Validator

from .config import ConfigError

WHY_FIELDS = {"line", "match"}
DEFAULT_WINDOW = 20


@dataclass(frozen=True)
class Detector:
    id: str
    tag: str
    paths: tuple[str, ...]
    weight: float
    regex: str | None = None
    ast_grep: str | None = None
    language: str | None = None
    exclude: tuple[str, ...] = ()
    verdict_hint: str | None = None
    window: int = DEFAULT_WINDOW
    why: str | None = None


@dataclass(frozen=True)
class Profile:
    stack: tuple[str, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    detectors: tuple[Detector, ...] = ()
    ignore: tuple[str, ...] = ()
    version: int = 1
    written_at: str | None = None
    head_sha: str | None = None

    def role_for(self, path: str) -> str | None:
        """The role of the longest dir in `roles` that holds `path` ("." is the root)."""
        best = None
        for d in self.roles:
            key = d.strip("/")
            if key in ("", "."):
                hit = 0
            elif path == key or path.startswith(key + "/"):
                hit = len(key) + 1
            else:
                continue
            if best is None or hit > best[0]:
                best = (hit, d)
        return self.roles[best[1]] if best else None

    def ignores(self, path: str) -> bool:
        return any(glob_matcher(g)(path) for g in self.ignore)


# ---------- globs ----------


def _glob_regex(glob: str) -> str:
    if glob.startswith("/") or ".." in glob.split("/"):
        raise ValueError("a glob must be relative and must not contain '..'")
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = glob.find("]", i + 2)
            if j < 0:
                raise ValueError("unclosed '[' in glob")
            body = glob[i + 1 : j]
            body = "^" + body[1:] if body.startswith("!") else body
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    rx = "".join(out)
    return rx if "/" in glob else "(?:.*/)?" + rx


@cache
def glob_matcher(glob: str):
    """A function path -> bool for `glob`. Raises ValueError for a bad glob."""
    try:
        rx = re.compile(_glob_regex(glob) + r"\Z")
    except re.error as e:
        raise ValueError(f"bad glob: {e}") from e
    return lambda path: rx.match(path) is not None


# ---------- parsing ----------


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((files("codescroll") / "schema" / "profile.schema.json").read_text())
    )


def _where(err, raw: dict) -> str:
    path = list(err.absolute_path)
    if len(path) >= 2 and path[0] == "detectors" and isinstance(path[1], int):
        dets = raw.get("detectors")
        did = dets[path[1]].get("id") if isinstance(dets[path[1]], dict) else None
        label = f"detector '{did}'" if isinstance(did, str) else f"detector #{path[1] + 1}"
        return " ".join([label, *map(str, path[2:])]).strip()
    return ".".join(map(str, path)) or "profile"


def _message(err) -> str:
    if err.validator == "oneOf" and list(err.absolute_path)[-1:] == ["match"]:
        return "match needs exactly one of regex or ast_grep"
    return err.message


def _fail(repo: str, where: str, msg: str):
    raise ConfigError(f"profile '{repo}': {where}: {msg}")


def _check_glob(repo: str, where: str, glob: str) -> None:
    try:
        glob_matcher(glob)
    except ValueError as e:
        _fail(repo, where, f"{e} ({glob!r})")


def _check_why(repo: str, where: str, why: str) -> None:
    for _, name, spec, conv in string.Formatter().parse(why):
        if name is not None and (name not in WHY_FIELDS or spec or conv):
            _fail(repo, where, f"why may only use {{line}} and {{match}}, not {{{name}}}")


def parse(raw, repo: str) -> Profile:
    """Validate a profile mapping and build a `Profile`. Raises `ConfigError`."""
    if raw is None:
        return Profile()
    if not isinstance(raw, dict):
        _fail(repo, "profile", "must be a mapping")
    errors = sorted(_validator().iter_errors(raw), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        e = errors[0]
        _fail(repo, _where(e, raw), _message(e))
    seen: set[str] = set()
    dets = []
    for d in raw.get("detectors") or []:
        did, match = d["id"], d["match"]
        where = f"detector '{did}'"
        if did in seen:
            _fail(repo, where, "duplicate detector id")
        seen.add(did)
        for key in ("paths", "exclude"):
            for g in match.get(key) or []:
                _check_glob(repo, f"{where} match.{key}", g)
        if "regex" in match:
            try:
                regex.compile(match["regex"])
            except regex.error as e:
                _fail(repo, where, f"bad regex: {e}")
        elif not match.get("language"):
            _fail(repo, where, "an ast_grep rule needs match.language")
        if d.get("why"):
            _check_why(repo, where, d["why"])
        dets.append(
            Detector(
                id=did,
                tag=d["tag"],
                paths=tuple(match["paths"]),
                weight=float(d["weight"]),
                regex=match.get("regex"),
                ast_grep=match.get("ast_grep"),
                language=match.get("language"),
                exclude=tuple(match.get("exclude") or ()),
                verdict_hint=d.get("verdict_hint"),
                window=d.get("window", DEFAULT_WINDOW),
                why=d.get("why"),
            )
        )
    for g in raw.get("ignore") or []:
        _check_glob(repo, "ignore", g)
    return Profile(
        stack=tuple(raw.get("stack") or ()),
        roles=dict(raw.get("roles") or {}),
        detectors=tuple(dets),
        ignore=tuple(raw.get("ignore") or ()),
        version=raw.get("version", 1),
        written_at=raw.get("written_at"),
        head_sha=raw.get("head_sha"),
    )


def load_profiles(root: Path) -> dict[str, Profile]:
    """Every `config/profiles/<repo>.yaml` under `root`, by repo name."""
    folder = Path(root) / "config" / "profiles"
    out: dict[str, Profile] = {}
    if not folder.is_dir():
        return out
    for file in sorted(folder.glob("*.yaml")):
        try:
            data = yaml.safe_load(file.read_text())
        except yaml.YAMLError as e:
            raise ConfigError(f"invalid YAML in {file}: {e}") from e
        try:
            out[file.stem] = parse(data, file.stem)
        except ConfigError as e:
            raise ConfigError(f"{e} ({file})") from e
    return out
