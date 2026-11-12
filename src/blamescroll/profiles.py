"""Repo profiles: per-repo detector rules kept as data.

A profile lives in `local/profiles/<repo>.yaml` inside Blamescroll, never in the user's repo.
It holds the stack, a role per directory, detector rules, and the file set: `scan` globs (files
that are read), `ignore` globs (never read) and `kinds` (test, fixture, generated, docs,
vendored). `FileSet` is the one classifier; the bootstrap values for a repo with no profile
are in `config/scan_defaults.yaml`. A profile key replaces the bootstrap key; an absent key
falls back to it. Rules are data:
a regex or an ast-grep pattern plus path globs. A profile may also carry `queries`: a
tree-sitter tags query per grammar (see structure.py), so a stack we do not ship can still be
read by structure. Blamescroll never runs code from a profile.
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
KINDS = ("test", "fixture", "generated", "docs", "vendored")
KIND_ORDER = ("vendored", "generated", "fixture", "test", "docs")  # first match wins
UNMINED = frozenset({"generated", "vendored", "fixture"})  # read, classified, never mined
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
class Sink:
    pattern: str
    kind: str = "other"


@dataclass(frozen=True)
class Convention:
    name_regex: str
    means: str  # effectful | pure


@dataclass(frozen=True)
class Profile:
    stack: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()  # free text, e.g. which analyzer made the submitted facts
    roles: dict[str, str] = field(default_factory=dict)
    detectors: tuple[Detector, ...] = ()
    ignore: tuple[str, ...] | None = None  # None: not set, the bootstrap ignore applies
    scan: tuple[str, ...] | None = None
    kinds: dict[str, tuple[str, ...]] | None = None
    generated_markers: tuple[str, ...] | None = None
    queries: dict[str, str] = field(default_factory=dict)  # grammar -> tree-sitter tags query
    sinks: tuple[Sink, ...] = ()  # calls with an effect (conventions.py)
    conventions: tuple[Convention, ...] = ()
    nil_guards: tuple[str, ...] = ()  # regexes that count as a nil check
    nil_markers: tuple[str, ...] = ()  # plain text in a returns type that means "may be nil"
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
        return any(glob_matcher(g)(path) for g in self.ignore or ())


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


# ---------- file set ----------


def _any(matchers, path: str) -> bool:
    return any(m(path) for m in matchers)


@dataclass(frozen=True)
class FileSet:
    """Which files are read and what kind each is. Built by `fileset_for`.

    A file is read iff it matches `scan` and not `ignore`. `kind` classifies it. Generated,
    vendored and fixture files are read and classified but never mined (`mined`)."""

    scan: tuple[str, ...]
    ignore: tuple[str, ...]
    kinds: dict[str, tuple[str, ...]]
    markers: tuple[str, ...]
    noise: tuple[str, ...]

    def _m(self, globs):
        return [glob_matcher(g) for g in globs]

    def ignored(self, path: str) -> bool:
        return _any(self._m(self.ignore), path)

    def reads(self, path: str) -> bool:
        return _any(self._m(self.scan), path) and not self.ignored(path)

    def matches(self, path: str, kind: str) -> bool:
        return _any(self._m(self.kinds.get(kind, ())), path)

    def kind(self, path: str) -> str | None:
        """test, fixture, generated, docs or vendored; None for a plain source file."""
        return next((k for k in KIND_ORDER if self.matches(path, k)), None)

    def is_test(self, path: str) -> bool:
        return self.matches(path, "test")

    def mined(self, path: str) -> bool:
        return self.kind(path) not in UNMINED

    def is_code_dir(self, d: str) -> bool:
        """True when files in dir `d` are neither ignored nor of any kind."""
        probe = f"{d}/x" if d not in ("", ".") else "x"
        return not self.ignored(probe) and self.kind(probe) is None

    def hidden_from_map(self, d: str) -> bool:
        """A dir the repo map leaves out: ignored, fixture, generated or vendored."""
        probe = f"{d}/x" if d not in ("", ".") else "x"
        return self.ignored(probe) or self.kind(probe) in UNMINED

    def is_noise(self, path: str) -> bool:
        """Never a lead: ignored, or a lockfile, source map or binary asset."""
        return self.ignored(path) or _any(self._m(self.noise), path)

    def has_generated_marker(self, lines) -> bool:
        head = "\n".join(lines[:5])
        return any(re.search(m, head, re.IGNORECASE) for m in self.markers)


@cache
def default_scan_defaults() -> dict:
    from .config import load_scan_defaults

    return load_scan_defaults()


def fileset_for(profile: Profile | None, defaults: dict | None = None) -> FileSet:
    """The file set of `profile`. A key the profile sets replaces the bootstrap key; a key it
    leaves out falls back to `defaults` (config/scan_defaults.yaml). No merging."""
    d = defaults or default_scan_defaults()
    p = profile or Profile()

    def pick(mine, key):
        return (d.get(key) or ()) if mine is None else mine

    kinds = (d.get("kinds") or {}) if p.kinds is None else p.kinds
    return FileSet(
        scan=tuple(pick(p.scan, "scan")),
        ignore=tuple(pick(p.ignore, "ignore")),
        kinds={k: tuple(v or ()) for k, v in kinds.items()},
        markers=tuple(pick(p.generated_markers, "generated_markers")),
        noise=tuple(d.get("noise") or ()),
    )


# ---------- parsing ----------


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((files("blamescroll") / "schema" / "profile.schema.json").read_text())
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


def _check_regex(repo: str, where: str, rx: str) -> None:
    try:
        regex.compile(rx)
    except regex.error as e:
        _fail(repo, where, f"bad regex: {e} ({rx!r})")


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
    for key in ("ignore", "scan"):
        for g in raw.get(key) or []:
            _check_glob(repo, key, g)
    for kind, globs in (raw.get("kinds") or {}).items():
        for g in globs:
            _check_glob(repo, f"kinds.{kind}", g)
    for rx in raw.get("generated_markers") or []:
        try:
            re.compile(rx)
        except re.error as e:
            _fail(repo, "generated_markers", f"bad regex: {e} ({rx!r})")

    for i, sk in enumerate(raw.get("sinks") or []):
        _check_regex(repo, f"sinks[{i}]", sk["pattern"])
    for i, cv in enumerate(raw.get("conventions") or []):
        _check_regex(repo, f"conventions[{i}]", cv["name_regex"])
    for rx in raw.get("nil_guards") or []:
        _check_regex(repo, "nil_guards", rx)

    def opt(key):
        return tuple(raw[key] or ()) if raw.get(key) is not None else None

    return Profile(
        stack=tuple(raw.get("stack") or ()),
        notes=tuple(raw.get("notes") or ()),
        roles=dict(raw.get("roles") or {}),
        detectors=tuple(dets),
        ignore=opt("ignore"),
        scan=opt("scan"),
        kinds=(
            {k: tuple(v) for k, v in raw["kinds"].items()} if raw.get("kinds") is not None else None
        ),
        generated_markers=opt("generated_markers"),
        queries=dict(raw.get("queries") or {}),
        sinks=tuple(Sink(s["pattern"], s.get("kind", "other")) for s in raw.get("sinks") or ()),
        conventions=tuple(
            Convention(c["name_regex"], c["means"]) for c in raw.get("conventions") or ()
        ),
        nil_guards=tuple(raw.get("nil_guards") or ()),
        nil_markers=tuple(raw.get("nil_markers") or ()),
        version=raw.get("version", 1),
        written_at=raw.get("written_at"),
        head_sha=raw.get("head_sha"),
    )


def load_profiles(root: Path) -> dict[str, Profile]:
    """Every `local/profiles/<repo>.yaml` under `root`, by repo name."""
    folder = Path(root) / "local" / "profiles"
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
