"""Shipped config files with the user's `local/` files merged over them (docs/config.md).

One rule for every file. A map merges key by key, at every depth. A list in a local file adds
its items to the shipped list. A scalar replaces. A key with no value is ignored. The explicit
forms: a list written as `{$remove: [...], $add: [...]}` or `{$replace: [...]}`; in a map,
`$remove: [key, ...]` drops shipped keys and `$replace: true` drops all of them.

`load(name)` gives the merged data of one file. It is cached until the shipped or the local
file changes (time and size), so a long-running process sees an edit at once. `load_config`
names the home that the readers without a Config use (`activate`).
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import config as _c
from .config import ConfigError

OPS = ("$add", "$remove", "$replace")
MERGE = (
    "maps merge key by key; a list adds its items to the shipped list; a scalar replaces. "
    "Explicit forms: a list as {$remove: [...], $add: [...]} or {$replace: [...]}; in a map, "
    "$remove: [keys] and $replace: true"
)
TAKES_EFFECT = (
    "The MCP tools read the files on every call, and the feed server reads them again when "
    "they change: no restart is needed. Two exceptions. settings.yaml: `server` and `render` "
    "values, `data_dir` and the worker intervals need a server restart (/mcp, gittok, "
    "Reconnect, or start `gittok serve` again). languages, queries, scan_defaults, "
    "file_types and a profile change what the next analysis finds: cards that exist stay "
    "as they are."
)


# ---------- the merge rule ----------


def _is_ops(value: Any) -> bool:
    return isinstance(value, dict) and any(k in OPS for k in value)


def _item_name(item: Any) -> Any:
    return item.get("name") if isinstance(item, dict) else None


def _list_ops(base: list, over: dict, where: str, removed: list | None) -> list:
    bad = [k for k in over if k not in OPS]
    if bad or not all(isinstance(v, list) for v in over.values()):
        raise ConfigError(
            f"'{where}' must be a list, or a map with $add, $remove or $replace (each a list)"
        )
    if "$replace" in over:
        if len(over) > 1:
            raise ConfigError(f"'{where}': $replace stands alone, without $add or $remove")
        if removed is not None:
            removed.append((where, "*"))
        return copy.deepcopy(over["$replace"])
    gone = over.get("$remove") or []
    out = [x for x in base if x not in gone and _item_name(x) not in gone]
    if removed is not None:
        removed += [(where, _item_name(x) or x) for x in base if x not in out]
    return _extend(out, over.get("$add") or [], where, removed)


def _extend(base: list, more: list, where: str, removed: list | None) -> list:
    out = list(base)
    for item in more:
        name = _item_name(item)
        at = next((i for i, x in enumerate(out) if name and _item_name(x) == name), None)
        if at is not None:
            out[at] = _merge(out[at], item, f"{where}.{name}", removed)
        elif item not in out:
            out.append(copy.deepcopy(item))
    return out


def _merge(base: Any, over: Any, where: str, removed: list | None) -> Any:
    if over is None:
        return base
    if isinstance(base, list):
        if isinstance(over, list):
            return _extend(base, over, where, removed)
        if isinstance(over, dict):
            return _list_ops(base, over, where, removed)
        return over
    if isinstance(over, dict):
        if base is None and _is_ops(over) and not isinstance(over.get("$replace"), bool):
            if "$add" in over or isinstance(over.get("$replace"), list):
                return _list_ops([], over, where, removed)
        out = dict(base) if isinstance(base, dict) else {}
        if over.get("$replace") is True:
            if removed is not None:
                removed += [(where, k) for k in out]
            out = {}
        elif "$replace" in over:
            raise ConfigError(f"'{where or 'the file'}': in a map, $replace must be `true`")
        if "$add" in over:
            raise ConfigError(f"'{where or 'the file'}' is a map: write its keys, not $add")
        drop = over.get("$remove") or []
        if not isinstance(drop, list):
            raise ConfigError(f"'{where or 'the file'}': $remove must be a list of keys")
        for k in drop:
            if k in out:
                del out[k]
                if removed is not None:
                    removed.append((where, k))
        for k, v in over.items():
            if k in OPS:
                continue
            sub = f"{where}.{k}" if where else str(k)
            merged = _merge(out.get(k), v, sub, removed)
            if merged is not None:
                out[k] = merged
        return out
    return copy.deepcopy(over)


def merge(base: Any, over: Any, removed: list | None = None) -> Any:
    """`over` (a local file) merged on `base` (the shipped file). `base` is not changed.
    `removed` collects (path, key or item name) for every shipped entry that was dropped."""
    return _merge(copy.deepcopy(base), over, "", removed)


# ---------- the files ----------


def _fail(msg: str) -> None:
    raise ConfigError(msg)


def _need(ok: bool, msg: str) -> None:
    if not ok:
        _fail(msg)


def _texts(value: Any, what: str) -> None:
    _need(
        isinstance(value, list) and all(isinstance(x, str) for x in value),
        f"'{what}' must be a list of text",
    )


def _regexes(value: Any, what: str) -> None:
    for pat in [value] if isinstance(value, str) else value:
        try:
            re.compile(pat)
        except (re.error, TypeError) as e:
            _fail(f"bad pattern in '{what}': {e}")


def _number(value: Any, what: str) -> None:
    _need(
        isinstance(value, int | float) and not isinstance(value, bool),
        f"'{what}' must be a number",
    )


def _map(value: Any, what: str) -> dict:
    _need(isinstance(value, dict), f"'{what}' must be a mapping")
    return value


def _check_languages(d: dict) -> None:
    langs = _map(d.get("languages") or {}, "languages")
    shared = _map(d.get("shared") or {}, "shared")
    _map(d.get("thresholds") or {}, "thresholds")
    for name, raw in (("shared", shared), *langs.items()):
        what = "shared" if raw is shared else f"language '{name}'"
        _need(isinstance(name, str), f"language name {name!r} must be text: put quotes around it")
        raw = _map(raw or {}, what)
        _need(raw is shared or bool(raw.get("extensions")), f"{what} is missing 'extensions'")
        for key, val in raw.items():
            if key not in _c._LANG_TEXT_KEYS and val is not None:
                _regexes(val, f"{what} {key}")


def _check_scan(d: dict) -> None:
    for key in ("scan", "ignore", "noise", "generated_markers"):
        _texts(d.get(key) or [], key)
    for kind, globs in _map(d.get("kinds") or {}, "kinds").items():
        _texts(globs or [], f"kinds.{kind}")
    _regexes(d.get("generated_markers") or [], "generated_markers")


def _check_file_types(d: dict) -> None:
    for key in ("highlight", "comment_prefixes", "todo_comment", "two_meanings"):
        _map(d.get(key) or {}, key)
    for ext, note in (d.get("two_meanings") or {}).items():
        _need(isinstance(note, str), f"'two_meanings.{ext}' must be a note")
    for key in (
        "file_words", "source_extensions", "noise_basenames", "manifests", "ast_grep_probe",
        "why_words", "doc_extensions",
    ):  # fmt: skip
        _texts(d.get(key) or [], key)
    for ext, name in (d.get("highlight") or {}).items():
        _need(isinstance(name, str), f"'highlight.{ext}' must be a language name")
    for ext, pre in (d.get("comment_prefixes") or {}).items():
        _texts(pre, f"comment_prefixes.{ext}")


ANALYZER_FIELDS = {"name", "languages", "binary", "gives", "how", "needs"}
FACT_KINDS = {"defines", "calls", "imports", "returns", "accepts"}


def _check_analyzers(d: dict) -> None:
    items = d.get("analyzers") or []
    _need(isinstance(items, list), "'analyzers' must be a list")
    for i, a in enumerate(items):
        where = f"analyzers[{_item_name(a) or i}]"
        _need(isinstance(a, dict), f"'{where}' must be a map")
        for key in ("name", "binary", "how"):
            _need(isinstance(a.get(key), str) and a[key].strip(), f"'{where}.{key}' is needed")
        for key in ("languages", "gives"):
            _texts(a.get(key) or [], f"{where}.{key}")
            _need(bool(a.get(key)), f"'{where}.{key}' is needed")
        bad = set(a.get("gives") or ()) - FACT_KINDS
        _need(not bad, f"'{where}.gives': unknown fact kinds {sorted(bad)}")


def _check_claims(d: dict) -> None:
    for kind, pats in _map(d.get("typed_phrases") or {}, "typed_phrases").items():
        _texts(pats or [], f"typed_phrases.{kind}")
        _regexes(pats or [], f"typed_phrases.{kind}")
    _texts(d.get("nilable_words") or [], "nilable_words")


SECRET_FLAGS = {"i": re.I, "s": re.S, "m": re.M}


def _check_secrets(d: dict) -> None:
    pats = d.get("patterns")
    _need(isinstance(pats, list), "'patterns' must be a list")
    for p in pats:
        _need(isinstance(p, dict) and isinstance(p.get("name"), str), "a pattern needs a 'name'")
        what = f"pattern '{p['name']}'"
        _need(isinstance(p.get("regex"), str), f"{what} needs a 'regex'")
        flags = p.get("flags", "")
        _need(
            isinstance(flags, str) and set(flags) <= set(SECRET_FLAGS),
            f"{what}: 'flags' may hold only i, s and m",
        )
        _regexes(p["regex"], what)
        group = p.get("group", 0)
        rx = re.compile(p["regex"])
        _need(
            (isinstance(group, int) and group <= rx.groups) or group in rx.groupindex,
            f"{what}: the regex has no group {group!r}",
        )
        _number(p.get("min_length", 0), f"{what} min_length")
        _number(p.get("min_entropy", 0), f"{what} min_entropy")
    if d.get("keep_prefix"):
        _regexes(d["keep_prefix"], "keep_prefix")


def _check_memes(d: dict) -> None:
    for tid, raw in _map(d.get("templates") or {}, "templates").items():
        _need(
            isinstance(tid, str), f"meme template name {tid!r} must be text: put quotes around it"
        )
        raw = _map(raw or {}, f"templates.{tid}")
        lines = raw.get("lines", 2)
        _need(
            isinstance(lines, int) and not isinstance(lines, bool) and lines > 0,
            f"'templates.{tid}.lines' must be a whole number above 0",
        )
        _texts(raw.get("fits") or [], f"templates.{tid}.fits")


def _check_defaults(d: dict) -> None:
    for key in ("categories", "tones", "visual_mix"):
        for k, v in _map(d.get(key) or {}, key).items():
            _number(v, f"{key}.{k}")


REWARD_MAPS = ("weights", "format_base_ms", "prior_sd", "lead_score", "slotting")


def _check_reward(d: dict) -> None:
    for key in REWARD_MAPS:
        if key in d:
            _map(d[key], key)
    for key in ("weights", "format_base_ms", "prior_sd", "lead_score"):
        for k, v in (d.get(key) or {}).items():
            _number(v, f"{key}.{k}")
    for key in (
        "skip_ms", "ms_per_word", "expected_ms_max", "half_life_days",
        "like_floor", "like_weight", "dislike_weight",
    ):  # fmt: skip
        if key in d:
            _number(d[key], key)
    # The model divides by these: 0 would stop learning with a ZeroDivisionError.
    for k, v in (d.get("prior_sd") or {}).items():
        _need(v > 0, f"'prior_sd.{k}' must be above 0")
    if "half_life_days" in d:
        _need(d["half_life_days"] > 0, "'half_life_days' must be above 0")
    for pair in d.get("crosses") or []:
        _need(
            isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair),
            f"crosses: each item is a pair of feature names, not {pair!r}",
        )


def _check_personas(d: dict) -> None:
    for handle, raw in _map(d.get("personas") or {}, "personas").items():
        _need(
            isinstance(handle, str),
            f"persona name {handle!r} must be text, but YAML reads it as "
            f"{type(handle).__name__}. Put quotes around it",
        )
        raw = _map(raw or {}, f"persona '{handle}'")
        for req in ("name", "voice"):
            _need(req in raw, f"persona '{handle}' is missing '{req}'")


def _check_queries(d: dict) -> None:
    for name, raw in _map(d.get("languages") or {}, "languages").items():
        raw = _map(raw or {}, f"languages.{name}")
        _map(raw.get("extensions") or {}, f"languages.{name}.extensions")
        _need(bool(raw.get("extensions")), f"language '{name}' is missing 'extensions'")
    generic = _map(d.get("generic") or {}, "generic")
    for key in ("nesting_regex", "branch_regex", "import_split"):
        if generic.get(key):
            _regexes(generic[key], f"generic.{key}")
    _map(d.get("text_fallback") or {}, "text_fallback")
    _map(d.get("embedded") or {}, "embedded")
    _map(d.get("path_normalize") or {}, "path_normalize")
    _texts(d.get("index_files") or [], "index_files")


@dataclass(frozen=True)
class FileSpec:
    name: str
    rel: str  # under config/ and under local/
    what: str
    edited_by: str
    shipped: bool = True
    # Path ("a.*.b", "" is the top level) -> the keys allowed there. None: the shipped keys.
    keys: dict[str, frozenset | None] = field(default_factory=dict)
    check: Callable[[dict], None] | None = None
    protected: tuple[str, ...] = ()  # lists whose shipped items go one by one, by name
    merge: str = MERGE
    layered: bool = False  # a `<shared>/config/` file that is not the shipped one is a layer too
    local: str = ""  # the local path as shown to the user, when it is not local/<rel>


def examples() -> dict[str, str]:
    """One small local override file for each config file, as text (package data)."""
    from importlib.resources import files

    text = (files("gittok") / "prompts" / "config_examples.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


BY_FILE_EDIT = "you, or the agent on your request: it edits the local file and runs check_config"


def _spec(name: str, what: str, keys: dict, check=None, **kw) -> FileSpec:
    return FileSpec(
        name=name,
        rel=kw.pop("rel", f"{name}.yaml"),
        what=what,
        edited_by=kw.pop("edited_by", BY_FILE_EDIT),
        keys={k: (None if v is None else frozenset(v)) for k, v in keys.items()},
        check=check,
        **kw,
    )


_REWARD_KEYS = (
    "skip_ms", "weights", "ms_per_word", "expected_ms_max", "format_base_ms",
    "like_floor", "like_weight", "dislike_weight", "prior_sd", "crosses", "lead_score",
    "half_life_days", "slotting",
)  # fmt: skip

FILES: dict[str, FileSpec] = {
    s.name: s
    for s in (
        FileSpec(
            name="settings",
            rel="settings.yaml",
            what="Server, agent, analysis, render and clean-up settings",
            edited_by="you, or the agent on your request (file edit); set_lan writes server.lan",
            merge=(
                "a top-level key replaces; inside a section (server, agent, ...) each key "
                "replaces on its own, a list included"
            ),
        ),
        _spec(
            "personas",
            "The cast: display name, voice and bio of each persona",
            {"": {"personas"}, "personas.*": {"name", "voice", "bio"}},
            _check_personas,
            edited_by="the edit_persona tool, `gittok persona edit`, or you",
        ),
        _spec(
            "defaults",
            "The starting mix of categories and tones, the image share, exploration",
            {
                "": {"categories", "tones", "visual_mix"},
                "categories": None,
                "tones": None,
                "visual_mix": None,
            },
            _check_defaults,
        ),
        _spec(
            "reward",
            "Reward weights, like and 👎 weights, read times, model priors, decay, lead score, "
            "slotting",
            {"": _REWARD_KEYS, "weights": None, "prior_sd": None},
            _check_reward,
            layered=True,
        ),
        _spec(
            "scan_defaults",
            "The file set of a repo with no profile: scan, ignore, kinds, noise",
            {"": _c._SCAN_KEYS, "kinds": {"test", "fixture", "generated", "vendored", "docs"}},
            _check_scan,
        ),
        _spec(
            "file_types",
            "Extension tables: highlight names, source and doc extensions, manifests",
            {"": _c._FILE_TYPE_KEYS, "todo_comment": {"prefixes", "words"}},
            _check_file_types,
        ),
        _spec(
            "languages",
            "Regex patterns per language for the candidate miners, and their thresholds",
            {
                "": {"languages", "thresholds", "shared"},
                "thresholds": None,
                "shared": _c._LANG_KEYS,
                "languages.*": _c._LANG_KEYS,
            },
            _check_languages,
        ),
        _spec(
            "queries",
            "Tree-sitter languages: shape rules per language, and one tags query per grammar",
            {
                "": {
                    "generic",
                    "text_fallback",
                    "path_normalize",
                    "index_files",
                    "embedded",
                    "languages",
                }  # fmt: skip
            },
            _check_queries,
            rel="queries/languages.yaml",
            local="local/queries/languages.yaml and local/queries/<grammar>.scm",
            merge=MERGE + ". A local/queries/<grammar>.scm file replaces the shipped query whole",
        ),
        _spec(
            "analyzers",
            "Code analyzers per language, for the profiling skill's analyzer facts",
            {"": {"analyzers"}, "analyzers.*": ANALYZER_FIELDS},
            _check_analyzers,
        ),
        _spec(
            "claims",
            "The phrases that make a typed claim, and the words that mean 'may be nil'",
            {"": {"typed_phrases", "nilable_words"}, "typed_phrases": None},
            _check_claims,
        ),
        _spec(
            "secrets",
            "The patterns of the secret detector (what is masked in repo text)",
            {
                "": {"keep_prefix", "patterns"},
                "patterns.*": {"name", "regex", "flags", "group", "min_length", "min_entropy"},
            },
            _check_secrets,
            protected=("patterns",),
            merge=(
                MERGE + ". `patterns` is protected: a pattern with a new name is added, one "
                "with a shipped name changes it, and a shipped pattern goes only by name "
                "(patterns: {$remove: [name]}); $replace is refused"
            ),
        ),
        _spec(
            "meme_templates",
            "The meme templates a writer may use",
            {"": {"templates"}, "templates.*": {"lines", "hint", "fits"}},
            _check_memes,
        ),
        FileSpec(
            name="repos",
            rel="repos.yaml",
            what="The repos and groups",
            edited_by="the add_repo, remove_repo, set_group and set_mascot tools, or you",
            shipped=False,
            merge="local only: nothing is shipped",
        ),
        FileSpec(
            name="mascots",
            rel="mascots.yaml",
            what="The mascots (one per repo) that illustration cards draw",
            edited_by="the set_mascot tool, `gittok mascot set`, or you",
            shipped=False,
            merge="local only: nothing is shipped",
        ),
        FileSpec(
            name="guidance",
            rel="guidance.md",
            edited_by="you, or the agent on your request (file edit)",
            what=(
                "Your own words for the card writers, as Markdown: tone, style, what to write "
                "about and what not"
            ),
            shipped=False,
            merge=(
                "local only: nothing is shipped. The text is added after GitTok's own guidance "
                "in every get_guidance reply"
            ),
        ),
        FileSpec(
            name="profiles",
            rel="profiles/<repo>.yaml",
            what="The profile of one repo: its file set, roles, rules and queries",
            edited_by="the gittok-profile-repo skill, through save_profile",
            shipped=False,
            merge=(
                "one repo only: scan, ignore, kinds and generated_markers each replace the "
                "value of scan_defaults; queries add a grammar for that repo"
            ),
        ),
    )
}


# ---------- loading ----------


class Loaded:
    """One merged file. `memo` keeps values derived from it (compiled patterns) for as long as
    the files do not change."""

    def __init__(self, data: dict, warnings: tuple[str, ...], shipped: dict, local: dict | None):
        self.data = data
        self.warnings = warnings
        self.shipped_data = shipped
        self.local_data = local
        self._memo: dict = {}

    def memo(self, key, build: Callable[[dict], Any]) -> Any:
        if key not in self._memo:
            self._memo[key] = build(self.data)
        return self._memo[key]


def _one_line(e: object) -> str:
    return " ".join(str(e).split())


def _read(path: Path, shown: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {shown}: {_one_line(e)}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read {shown}: {_one_line(e)}") from None


def _read_map(path: Path, shown: str) -> dict:
    data = _read(path, shown)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{shown} must be a mapping")
    return data


def _stamp(path: Path | None) -> tuple[int, int] | None:
    if path is None:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _allowed(spec: FileSpec, path: tuple[str, ...], shipped: dict) -> frozenset | None:
    """The keys allowed at `path`, or None when any key is."""
    for pattern, keys in spec.keys.items():
        parts = tuple(pattern.split(".")) if pattern else ()
        if len(parts) != len(path):
            continue
        if any(a != "*" and a != b for a, b in zip(parts, path, strict=True)):
            continue
        if keys is not None:
            return keys
        node: Any = shipped
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
        return frozenset(node) if isinstance(node, dict) else None
    return None


def _known_only(spec: FileSpec, data: Any, shipped: dict, path=(), unknown=None) -> Any:
    """`data` without the keys that the file's spec does not know; `unknown` collects them."""
    if isinstance(data, list):
        return [
            _known_only(spec, x, shipped, (*path, str(_item_name(x) or i)), unknown)
            for i, x in enumerate(data)
        ]
    if not isinstance(data, dict):
        return data
    allowed = _allowed(spec, path, shipped)
    out = {}
    for k, v in data.items():
        if k in OPS:  # $add holds whole items; $remove and $replace hold names or values
            add = k == "$add" and isinstance(v, list)
            out[k] = _known_only(spec, v, shipped, path, unknown) if add else v
        elif allowed is not None and k not in allowed:
            if unknown is not None:
                unknown.append(".".join((*path, str(k))))
        else:
            out[k] = _known_only(spec, v, shipped, (*path, str(k)), unknown)
    return out


def _guard(spec: FileSpec, over: dict, shown: str) -> None:
    """Refuse a local file that drops a protected list whole."""
    whole = over.get("$replace") is True or any(
        p in (over.get("$remove") or ()) for p in spec.protected
    )
    part = any(isinstance(over.get(p), dict) and "$replace" in over[p] for p in spec.protected)
    if whole or part:
        p = spec.protected[0]
        raise ConfigError(
            f"{shown} may not replace or remove the shipped `{p}` whole: that would turn "
            f"them all off without a word. Name each one to turn off: {p}: {{$remove: [name]}}"
        )


def _overlay(spec: FileSpec, base: dict, file: Path, shown: str):
    """(merged data, warnings) of the local file `file` over `base`."""
    over = _read_map(file, shown)
    unknown: list[str] = []
    over = _known_only(spec, over, base, (), unknown)
    warnings = [f"unknown {spec.name} key '{k}' in {shown} (ignored)" for k in unknown]
    if spec.protected:
        _guard(spec, over, shown)
    if any(k in OPS for k in over):
        # The code reads the top-level keys of a file, so they stay.
        raise ConfigError(
            f"$remove and $replace work inside a key, not at the top of the file ({shown})"
        )
    removed: list = []
    before = {p: {_item_name(x): x for x in base.get(p) or ()} for p in spec.protected}
    try:
        data = merge(base, over, removed)
    except ConfigError as e:
        raise ConfigError(f"{e} ({shown})") from None
    for p in spec.protected:
        for where, name in removed:
            if where == p:
                warnings.append(
                    f"shipped {spec.name} pattern '{name}' is turned off in {shown}: "
                    "less text is masked"
                )
        for item in data.get(p) or ():
            old = before[p].get(_item_name(item))
            if old is not None and old != item:
                warnings.append(
                    f"shipped {spec.name} pattern '{_item_name(item)}' is changed in {shown}"
                )
    return data, warnings


def _shown(path: Path) -> str:
    parts = path.parts
    for folder in ("local", "config"):
        if folder in parts:
            at = len(parts) - 1 - parts[::-1].index(folder)
            return "/".join(parts[at:])
    return str(path)


_cache: dict[tuple, tuple[tuple, Loaded | ConfigError]] = {}
_active: tuple[Path, Path | None] | None = None
_resolved: dict[tuple[str | None, str], tuple[Path, Path | None]] = {}


def activate(shared: Path | None, home: Path | None) -> None:
    """Name the roots that readers without a Config use from now on (`load_config` calls it)."""
    global _active
    _active = (Path(shared) if shared else _c.shipped_root(), Path(home) if home else None)


def deactivate() -> None:
    global _active
    _active = None


def roots() -> tuple[Path, Path | None]:
    """(shared root, home or None): the active ones, else those of the current directory, else
    the shipped files alone."""
    if _active is not None:
        return _active
    key = (os.environ.get("GITTOK_ROOT"), os.getcwd())
    if key not in _resolved:
        try:
            _resolved[key] = _c.resolve_roots()
        except ConfigError:
            _resolved[key] = (_c.shipped_root(), None)
    return _resolved[key]


def _paths(spec: FileSpec, shared: Path, home: Path | None) -> list[tuple[Path, str]]:
    """The files of one config file, bottom layer first, each with its role: `base` (read
    strictly, it must exist), `layer` and `local` (merged over it when they exist)."""
    shipped_file = _c.shipped_root() / "config" / spec.rel
    own = shared / "config" / spec.rel
    if not spec.shipped:
        layers = []
    elif own == shipped_file or not own.is_file():
        layers = [(shipped_file, "base")]
    elif spec.layered:
        layers = [(shipped_file, "base"), (own, "layer")]
    else:
        layers = [(own, "base")]  # a test root with its own file: it stands for the shipped one
    if home is not None:
        layers.append((home / "local" / spec.rel, "local"))
    return layers


_UNSET: Any = object()


def load(name: str, shared: Path | None = None, home: Any = _UNSET) -> Loaded:
    """The merged data of the config file `name`. With no roots given, the active ones."""
    spec = FILES[name]
    if home is _UNSET and shared is None:
        shared, home = roots()
    elif home is _UNSET:
        home = None
    shared = Path(shared) if shared else _c.shipped_root()
    home = Path(home) if home else None
    paths = _paths(spec, shared, home)
    stamps = tuple(_stamp(p) for p, _ in paths)
    key = (name, str(shared), str(home))
    hit = _cache.get(key)
    if hit is None or hit[0] != stamps:
        try:
            hit = (stamps, _load(spec, paths, stamps))
        except ConfigError as e:  # kept too: a broken file is not parsed on every call
            hit = (stamps, e)
        _cache[key] = hit
    if isinstance(hit[1], ConfigError):
        raise ConfigError(str(hit[1]))
    return hit[1]


def _load(spec: FileSpec, paths: list[tuple[Path, str]], stamps: tuple) -> Loaded:
    base: dict = {}
    warnings: list[str] = []
    local_data = None
    shipped_data: dict = {}
    for (path, role), stamp in zip(paths, stamps, strict=True):
        if stamp is None:
            if role == "base":
                raise ConfigError(f"missing config file: {path}")
            continue
        shown = _shown(path)
        if role == "base":
            base = _read_map(path, str(path))
            unknown: list[str] = []
            base = _known_only(spec, base, base, (), unknown)
            if unknown:
                raise ConfigError(f"unknown key '{unknown[0]}' in {spec.rel} ({path})")
            _validate(spec, base, str(path))
            shipped_data = base
            continue
        if role == "local":
            local_data = _read(path, shown)
        base, more = _overlay(spec, base, path, shown)
        _validate(spec, base, shown)
        warnings += more
    return Loaded(base, tuple(warnings), shipped_data, local_data)


def _validate(spec: FileSpec, data: dict, shown: str) -> None:
    if spec.check is None:
        return
    try:
        spec.check(data)
    except ConfigError as e:
        raise ConfigError(f"{_one_line(e)} ({shown})") from None


def shipped(name: str) -> dict:
    """The shipped data of one file, with no local file."""
    return load(name, home=None).shipped_data


def current(name: str) -> Loaded:
    """The merged file `name` for the active roots. When its local file is broken, the
    shipped file alone: `load_config` reports the error, and a reader far from it (the
    secret detector) must still work."""
    try:
        return load(name)
    except ConfigError:
        return load(name, home=None)


def data(name: str) -> dict:
    """The merged data of `name` for the active roots. Do not change the result."""
    return current(name).data


def derived(names: str | tuple[str, ...], key, build: Callable[..., Any]) -> Any:
    """`build(data, ...)` of the named files for the active roots, kept until one of them
    changes. For compiled patterns and lookup tables."""
    names = (names,) if isinstance(names, str) else names
    loaded = tuple(current(n) for n in names)
    slot = loaded[0]._memo.get((key, names))
    if slot is not None and all(a is b for a, b in zip(slot[0], loaded, strict=True)):
        return slot[1]
    value = build(*(ld.data for ld in loaded))
    loaded[0]._memo[(key, names)] = (loaded, value)
    return value


# ---------- queries: one tags query per grammar ----------


def query_file(grammar: str, shared: Path | None = None, home: Any = _UNSET) -> Path | None:
    """The tags query of `grammar`: local/queries/<grammar>.scm, else the shipped one."""
    if home is _UNSET and shared is None:
        shared, home = roots()
    elif home is _UNSET:
        home = None
    shared = Path(shared) if shared else _c.shipped_root()
    places = [shared / "config" / "queries", _c.shipped_root() / "config" / "queries"]
    if home:
        places.insert(0, Path(home) / "local" / "queries")
    for d in places:
        f = d / f"{grammar}.scm"
        if f.is_file():
            return f
    return None


def local_queries(home: Path | None) -> list[Path]:
    d = Path(home) / "local" / "queries" if home else None
    return sorted(d.glob("*.scm")) if d and d.is_dir() else []


# ---------- what an agent reads: the list, one value, a check ----------


def _local_shown(spec: FileSpec) -> str:
    return spec.local or f"local/{spec.rel}"


GUIDANCE_MAX_CHARS = 6000  # a longer local/guidance.md is cut: get_guidance has a size limit


def local_guidance(home: Path | None, cap: bool = True) -> str | None:
    """The text of `local/guidance.md`, stripped; None when there is none or it is empty.
    With `cap`, at most GUIDANCE_MAX_CHARS (what the writers get)."""
    file = Path(home) / "local" / "guidance.md" if home else None
    if not file or not file.is_file():
        return None
    try:
        text = file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"local/guidance.md: cannot read it ({e})") from None
    if not text:
        return None
    return text[:GUIDANCE_MAX_CHARS] if cap else text


def _guidance_warnings(home: Path) -> tuple[str, ...]:
    text = local_guidance(home, cap=False)
    if text and len(text) > GUIDANCE_MAX_CHARS:
        return (
            f"local/guidance.md has {len(text)} characters: the writers get only the first "
            f"{GUIDANCE_MAX_CHARS}. Make it shorter.",
        )
    return ()


def describe(shared: Path | None, home: Path | None) -> list[dict]:
    """One row per config file: where it is shipped, where its local file goes, the rule."""
    rows = []
    shown = examples()
    for spec in FILES.values():
        if spec.name == "profiles":
            d = Path(home) / "local" / "profiles" if home else None
            exists = bool(d and d.is_dir() and any(d.glob("*.yaml")))
        elif spec.name == "queries":
            exists = bool(home) and (
                (Path(home) / "local" / spec.rel).is_file() or bool(local_queries(home))
            )
        else:
            exists = bool(home) and (Path(home) / "local" / spec.rel).is_file()
        rows.append(
            {
                "file": spec.name,
                "what": spec.what,
                "shipped": f"config/{spec.rel}" if spec.shipped else None,
                "local": _local_shown(spec),
                "local_exists": exists,
                "merge": spec.merge,
                "edited_by": spec.edited_by,
                "takes_effect": _effect(spec.name),
                "example": shown[spec.name],
            }
        )
    return rows


def _effect(name: str) -> str:
    if name == "settings":
        return (
            "the next tool call; `server`, `render`, `data_dir` and worker intervals need a "
            "server restart (/mcp, gittok, Reconnect)"
        )
    if name in ("languages", "queries", "scan_defaults", "file_types", "profiles"):
        return "the next analysis (the next cards); no restart"
    if name == "repos":
        return "the next tool call; no restart"
    if name == "guidance":
        return "the next get_guidance call (the next cards); no restart"
    return "at once: the next tool call and the next feed request; no restart"


def _walk(node: Any, key: str, name: str) -> Any:
    for part in key.split("/") if "/" in key else key.split("."):
        if isinstance(node, list):
            node = next((x for x in node if _item_name(x) == part), _UNSET)
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            node = _UNSET
        if node is _UNSET:
            return _UNSET
    return node


def _settings_layers(shared: Path, home: Path | None) -> tuple[dict, dict | None, dict]:
    base = _read_map(shared / "config" / "settings.yaml", "config/settings.yaml")
    file = Path(home) / "local" / "settings.yaml" if home else None
    local = _read_map(file, "local/settings.yaml") if file and file.is_file() else None
    merged = dict(base)
    for key, val in (local or {}).items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        elif val is not None or key == "data_dir":
            merged[key] = val
    return base, local, merged


def get(shared: Path | None, home: Path | None, name: str, key: str | None = None) -> dict:
    """The shipped value, the local value and the effective (merged) value of a config file,
    or of one key in it. `key` is a dotted path ("weights.like"); use "/" between the parts
    when a part has a dot ("highlight/.py"). A list item is named by its `name`."""
    spec = FILES.get(name)
    if spec is None or spec.name == "profiles":
        known = ", ".join(n for n in FILES if n != "profiles")
        raise ConfigError(f"unknown config file '{name}'. Known files: {known}")
    shared = Path(shared) if shared else _c.shipped_root()
    if name == "settings":
        base, local, effective = _settings_layers(shared, home)
    elif spec.shipped:
        ld = load(name, shared, home)
        base, local, effective = ld.shipped_data, ld.local_data, ld.data
    elif name == "guidance":
        base, local = None, local_guidance(home, cap=False)
        effective = local
    else:
        file = Path(home) / "local" / spec.rel if home else None
        local = _read_map(file, f"local/{spec.rel}") if file and file.is_file() else None
        base, effective = None, local
    out = {"file": name, "key": key}
    values = {"shipped": base, "local": local, "effective": effective}
    if key:
        values = {k: _walk(v, key, name) for k, v in values.items()}
        if values["effective"] is _UNSET and values["shipped"] is _UNSET:
            raise ConfigError(f"no key '{key}' in the config file '{name}'")
        values = {k: (None if v is _UNSET else v) for k, v in values.items()}
    return {**out, **values, "local_path": _local_shown(spec), "merge": spec.merge}


def check(shared: Path | None, home: Path | None) -> dict:
    """Load every config file from disk again. Returns ok, errors (one line each, with the
    file), warnings (ignored keys, a secret pattern turned off), the local files found, and
    what takes effect when."""
    shared = Path(shared) if shared else _c.shipped_root()
    errors: list[str] = []
    warnings: list[str] = []
    for name, spec in FILES.items():
        if not spec.shipped or name == "settings":
            continue
        try:
            warnings += load(name, shared, home).warnings
        except ConfigError as e:
            errors.append(_one_line(e))
    if not any("queries/languages.yaml" in e for e in errors):
        errors += _query_errors(shared, home)
    if home is not None:
        from .profiles import load_profiles

        home = Path(home).resolve()
        for part in (
            lambda: _c._load_settings(home, shared)[1],
            lambda: _c._load_repos(home) and (),
            lambda: _c._load_mascots(home) and (),
            lambda: load_profiles(home) and (),
            lambda: _guidance_warnings(home),
        ):
            try:
                warnings += [w for w in part() if w not in warnings]
            except ConfigError as e:
                errors.append(_one_line(e))
    found = []
    if home is not None:
        local = Path(home) / "local"
        found = sorted(
            f"local/{p.relative_to(local).as_posix()}"
            for pat in ("*.yaml", "*.md", "queries/*", "profiles/*.yaml")
            for p in local.glob(pat)
            if p.is_file()
        )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "local_files": found,
        "takes_effect": TAKES_EFFECT,
    }


def _query_errors(shared: Path, home: Path | None) -> list[str]:
    """One error for each local tags query that does not compile, or that no language uses."""
    from . import structure

    out = []
    try:
        langs = load("queries", shared, home).data.get("languages") or {}
    except ConfigError:
        return out
    grammars = {g for raw in langs.values() for g in (raw.get("extensions") or {}).values()}
    for file in local_queries(home):
        shown, grammar = _shown(file), file.stem
        if grammar not in grammars:
            out.append(
                f"{shown}: no language in queries/languages.yaml maps an extension to the "
                f"grammar '{grammar}', so the query is never used"
            )
            continue
        if not structure.available() or not structure.ready(grammar):
            continue  # cannot compile it here; `gittok structure --prefetch` gets the grammar
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            out.append(f"cannot read {shown}: {_one_line(e)}")
            continue
        why = structure.check_query(grammar, text)
        if why:
            out.append(f"{shown}: {_one_line(why)}")
    return out
