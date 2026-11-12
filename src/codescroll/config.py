"""Load CodeScroll configuration from the project's config/ directory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from functools import cache
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Repo:
    name: str
    path: Path
    ref: str = "HEAD"
    mascot: str | None = None
    group: str | None = None
    fetch: bool = False  # refresh the remote-tracking ref before analysis (docs/install.md)
    url: str | None = None  # web URL of the repo (GitHub); None means derive it from `origin`


def _as_bool(value: object, what: str, file: object) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{what} must be true or false ({file})")
    return value


@dataclass(frozen=True)
class Group:
    name: str
    repos: tuple[str, ...]
    standalone: bool = False


@dataclass(frozen=True)
class Persona:
    handle: str
    name: str
    voice: str
    bio: str | None = None


@dataclass(frozen=True)
class AgentSettings:
    default_count: int = 10
    max_count: int = 20
    per_day_runs: int = 4
    packet_size: int = 2
    target_runway_days: int = 3
    wake_cooldown_hours: int = 4  # least time between two feed-watch signals
    min_burn_per_day: int = 10
    min_run_count: int = 8
    lead_cooldown_days: int = 30
    subject_cooldown_days: int = 14  # a commit or path is the subject of one card per window
    min_spot_the_bug_per_run: float = 0.125  # share of a brief's cards reserved for spot_the_bug
    variant_min_reward: float = 0.6
    variant_after_days: int = 14
    variant_max_share: float = 0.2
    intro_share: float = 0.25
    scout_max: int = 60  # unrated candidates one scout_status call hands out
    scout_batch: int = 15  # candidates per scout subagent
    claim_checks: bool = True  # reject cards whose numbers, dates, or names git does not back
    require_facts: bool = False  # reject cards with a backticked identifier no listed fact covers
    require_claim_sources: bool = False  # reject (not warn) a why-sentence with no sourced claim


@dataclass(frozen=True)
class AnalysisSettings:
    history_window_days: int = 720
    churn_windows_days: tuple[int, ...] = (30, 90, 365)
    blame_max_files: int = 50
    blame_max_bytes: int = 2000000
    todo_max_hits: int = 150
    why_min_words: int = 25  # a commit body this long counts as an explanation
    candidates_per_tag: int = 40
    candidate_max_file_bytes: int = 200000
    candidate_max_files: int = 4000
    fetch_min_interval_s: int = 900  # at most one fetch per repo in this time
    facts_max_files: int = 4000  # syntax facts (facts.py): files read at head
    facts_max_commits: int = 300  # commits whose diffs map to definitions (newest first)
    facts_max_defs: int = 100000  # rows kept per repo, per table
    facts_max_calls: int = 400000
    facts_max_blob_bytes: int = 200000  # larger files are not parsed


@dataclass(frozen=True)
class ResearchSettings:
    max_output_bytes: int = 200000
    max_read_lines: int = 300
    redact_secrets: bool = True  # UNSAFE to turn off: repo text goes out as it is


@dataclass(frozen=True)
class RenderSettings:
    max_illustrations_per_run: int = 6
    memegen_url: str = "http://127.0.0.1:5001"
    mflux_model: str = "z-image-turbo"
    mflux_path: str = ""  # folder from `mflux-save -q N`; empty = quantize mflux_model per run
    mflux_steps: int = 8
    mflux_quantize: int = 8
    image_width: int = 768
    image_height: int = 960
    worker_interval_s: float = 5.0


@dataclass(frozen=True)
class GcSettings:
    seen_after_cards: int = 20
    liked_after_days: int = 90
    unseen_after_days: int = 45
    failed_after_days: int = 7
    srs_keep_days: int = 60
    events_after_days: int = 90
    run_files_after_days: int = 30
    social_after_days: int = 30
    leads_after_days: int = 180
    log_max_kb: int = 1024
    interval_s: float = 3600.0


@dataclass(frozen=True)
class Mascot:
    name: str
    repo: str | None
    style: str
    seed: int


@dataclass(frozen=True)
class MemeTemplate:
    id: str
    lines: int
    hint: str = ""
    fits: tuple[str, ...] = ()  # story types it suits; empty means any


@dataclass(frozen=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8008


@dataclass(frozen=True)
class ReposSettings:
    # Empty means: the parent directories of the repos already configured.
    allowed_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class UserSettings:
    # Names (as the history shows them) the reader commits under. Their blame share in a dir
    # is a small prior on novelty only (docs/learning.md section 14).
    git_identities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfilesSettings:
    max_hits: int = 200  # a profile rule with more hits than this is refused (too broad)
    max_ms: int = 5000  # a profile rule that runs longer than this is refused


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    server: ServerSettings
    agent: AgentSettings
    analysis: AnalysisSettings
    research: ResearchSettings
    render: RenderSettings = field(default_factory=RenderSettings)
    repos: ReposSettings = field(default_factory=ReposSettings)
    gc: GcSettings = field(default_factory=GcSettings)
    user: UserSettings = field(default_factory=UserSettings)
    profiles: ProfilesSettings = field(default_factory=ProfilesSettings)


@dataclass(frozen=True)
class Config:
    root: Path
    repos: dict[str, Repo]
    groups: dict[str, Group]
    settings: Settings
    defaults: dict
    personas: dict[str, Persona]
    mascots: dict[str, Mascot] = field(default_factory=dict)
    meme_templates: dict[str, MemeTemplate] = field(default_factory=dict)
    languages: dict = field(default_factory=dict)  # config/languages.yaml
    profiles: dict = field(default_factory=dict)  # repo -> profiles.Profile (local/profiles/)
    scan_defaults: dict = field(default_factory=dict)  # config/scan_defaults.yaml

    def repo(self, name: str) -> Repo:
        try:
            return self.repos[name]
        except KeyError:
            raise ConfigError(f"unknown repo: {name}") from None

    def profile(self, repo: str):
        """The repo's profile; an empty one (built-in detectors only) when it has none."""
        from .profiles import Profile

        return self.profiles.get(repo) or Profile()

    def fileset(self, repo: str):
        """The repo's file set: its profile's scan, ignore and kinds, else the bootstrap."""
        from .profiles import fileset_for

        return fileset_for(self.profile(repo), self.scan_defaults or None)

    def role_for(self, repo: str, path: str) -> str | None:
        """One-line purpose of the dir that holds `path`, from the repo's profile."""
        return self.profile(repo).role_for(path)


def project_root(start: Path | None = None) -> Path:
    env = os.environ.get("CODESCROLL_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "config" / "settings.yaml").is_file():
            return d
    raise ConfigError("project root not found: no config/settings.yaml in any parent directory")


def _read(path: Path, required: bool = False) -> Any:
    if not path.is_file():
        if required:
            raise ConfigError(f"missing config file: {path}")
        return None
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e


def _mapping(value: Any, what: str, file: Path) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{what} must be a mapping in {file}")
    return value


def _text_keys(data: dict, what: str, file: Path) -> dict:
    """YAML reads keys such as `on`, `null`, or `123` as non-text; refuse them."""
    for key in data:
        if not isinstance(key, str):
            raise ConfigError(
                f"{what} name {key!r} must be text, but YAML reads it as {type(key).__name__}. "
                f"Put quotes around it ({file})"
            )
    return data


def _check_keys(data: dict, allowed: set[str], what: str, file: Path) -> None:
    for key in data:
        if key not in allowed:
            raise ConfigError(f"unknown key '{key}' in {what} ({file})")


def _section(cls: type, data: Any, what: str, file: Path) -> Any:
    data = _mapping(data, what, file)
    _check_keys(data, {f.name for f in fields(cls)}, what, file)
    kwargs = dict(data)
    if "git_identities" in kwargs:
        ids = kwargs["git_identities"] or []
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ConfigError(f"{what}.git_identities must be a list of text ({file})")
        kwargs["git_identities"] = tuple(ids)
    if "churn_windows_days" in kwargs:
        kwargs["churn_windows_days"] = tuple(kwargs["churn_windows_days"])
    return cls(**kwargs)


def _repos_settings(data: Any, root: Path, file: Path) -> ReposSettings:
    data = _mapping(data, "settings.repos", file)
    _check_keys(data, {"allowed_roots"}, "settings.repos", file)
    raw = data.get("allowed_roots") or []
    if not isinstance(raw, list) or not all(isinstance(r, str) for r in raw):
        raise ConfigError(f"settings.repos.allowed_roots must be a list of paths ({file})")
    roots = []
    for r in raw:
        p = Path(r).expanduser()
        roots.append((p if p.is_absolute() else root / p).resolve())
    return ReposSettings(allowed_roots=tuple(roots))


_SETTINGS_KEYS = {
    "data_dir", "server", "agent", "analysis", "research", "render", "repos", "gc", "user",
    "profiles",
}  # fmt: skip


def _load_settings(root: Path) -> Settings:
    """config/settings.yaml, with the optional local/settings.yaml merged over it.

    Top-level keys replace; mapping sections merge key by key. Each file is checked on its
    own first, so an unknown key names the file that holds it.
    """
    base_file = root / "config" / "settings.yaml"
    local_file = root / "local" / "settings.yaml"
    base = _mapping(_read(base_file), "settings", base_file)
    local = _mapping(_read(local_file), "settings", local_file)
    _build_settings(base, root, base_file)
    if local:
        _build_settings(local, root, local_file)
    merged = dict(base)
    for key, val in local.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        elif val is not None or key == "data_dir":
            merged[key] = val
    return _build_settings(merged, root, local_file if local else base_file)


def _build_settings(data: dict, root: Path, file: Path) -> Settings:
    _check_keys(data, _SETTINGS_KEYS, "settings", file)
    data_dir = Path(str(data.get("data_dir", "data"))).expanduser()
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    return Settings(
        data_dir=data_dir.resolve(),
        server=_section(ServerSettings, data.get("server"), "settings.server", file),
        agent=_section(AgentSettings, data.get("agent"), "settings.agent", file),
        analysis=_section(AnalysisSettings, data.get("analysis"), "settings.analysis", file),
        research=_section(ResearchSettings, data.get("research"), "settings.research", file),
        render=_section(RenderSettings, data.get("render"), "settings.render", file),
        repos=_repos_settings(data.get("repos"), root, file),
        gc=_section(GcSettings, data.get("gc"), "settings.gc", file),
        user=_section(UserSettings, data.get("user"), "settings.user", file),
        profiles=_section(ProfilesSettings, data.get("profiles"), "settings.profiles", file),
    )


def _load_repos(root: Path) -> tuple[dict[str, Repo], dict[str, Group]]:
    file = root / "local" / "repos.yaml"  # optional: missing means no repos and no groups
    data = _mapping(_read(file), "repos.yaml", file)
    _check_keys(data, {"repos", "groups"}, "repos.yaml", file)
    raw_repos = _text_keys(_mapping(data.get("repos"), "repos", file), "repo", file)
    raw_groups = _text_keys(_mapping(data.get("groups"), "groups", file), "group", file)

    assigned: dict[str, str] = {}

    def assign(repo: str, group: str) -> None:
        if assigned.get(repo, group) != group:
            raise ConfigError(
                f"repo '{repo}' assigned to conflicting groups "
                f"'{assigned[repo]}' and '{group}' ({file})"
            )
        assigned[repo] = group

    groups: dict[str, Group] = {}
    for gname, raw in raw_groups.items():
        raw = _mapping(raw, f"group '{gname}'", file)
        _check_keys(raw, {"repos", "standalone"}, f"group '{gname}'", file)
        members = tuple(raw.get("repos") or ())
        for m in members:
            if m not in raw_repos:
                raise ConfigError(f"group '{gname}' references unknown repo: {m} ({file})")
            assign(m, gname)
        groups[gname] = Group(gname, members, bool(raw.get("standalone", False)))

    repos: dict[str, Repo] = {}
    for rname, raw in raw_repos.items():
        raw = _mapping(raw, f"repo '{rname}'", file)
        _check_keys(
            raw, {"path", "ref", "mascot", "group", "url", "fetch"}, f"repo '{rname}'", file
        )
        if not raw.get("path"):
            raise ConfigError(f"repo '{rname}' is missing 'path' ({file})")
        if raw.get("group") is not None:
            g = raw["group"]
            if g not in groups:
                raise ConfigError(f"repo '{rname}' references unknown group: {g} ({file})")
            assign(rname, g)
        repos[rname] = Repo(
            name=rname,
            path=Path(str(raw["path"])).expanduser().resolve(),
            ref=raw.get("ref", "HEAD"),
            mascot=raw.get("mascot"),
            group=assigned.get(rname),
            url=raw.get("url"),
            fetch=_as_bool(raw.get("fetch", False), f"repo '{rname}' fetch", file),
        )

    # repo-level group: keys add membership to the group
    for rname, repo in repos.items():
        if repo.group and rname not in groups[repo.group].repos:
            g = groups[repo.group]
            groups[repo.group] = Group(g.name, (*g.repos, rname), g.standalone)
    return repos, groups


def _overlay_entries(
    root: Path, fname: str, top: str, kind: str, allowed: set[str]
) -> dict[str, tuple[dict, Path]]:
    """Entries of `config/<fname>` with `local/<fname>` merged over them per name, field by field.

    Each entry comes with the file that last set it, for error messages.
    """
    out: dict[str, tuple[dict, Path]] = {}
    for folder in ("config", "local"):
        file = root / folder / fname
        data = _mapping(_read(file), fname, file)
        _check_keys(data, {top}, fname, file)
        for name, raw in _text_keys(_mapping(data.get(top), top, file), kind, file).items():
            raw = _mapping(raw, f"{kind} '{name}'", file)
            _check_keys(raw, allowed, f"{kind} '{name}'", file)
            out[name] = ({**out.get(name, ({}, file))[0], **raw}, file)
    return out


def _load_personas(root: Path) -> dict[str, Persona]:
    out: dict[str, Persona] = {}
    entries = _overlay_entries(
        root, "personas.yaml", "personas", "persona", {"name", "voice", "bio"}
    )
    for handle, (raw, file) in entries.items():
        for req in ("name", "voice"):
            if req not in raw:
                raise ConfigError(f"persona '{handle}' is missing '{req}' ({file})")
        out[handle] = Persona(handle, raw["name"], raw["voice"], raw.get("bio"))
    return out


def _load_mascots(root: Path) -> dict[str, Mascot]:
    out: dict[str, Mascot] = {}
    entries = _overlay_entries(root, "mascots.yaml", "mascots", "mascot", {"repo", "style", "seed"})
    for name, (raw, file) in entries.items():
        if not raw.get("style"):
            raise ConfigError(f"mascot '{name}' is missing 'style' ({file})")
        out[name] = Mascot(name, raw.get("repo"), raw["style"], int(raw.get("seed", 0)))
    return out


def _load_meme_templates(root: Path) -> dict[str, MemeTemplate]:
    file = root / "config" / "meme_templates.yaml"
    data = _mapping(_read(file), "meme_templates.yaml", file)
    _check_keys(data, {"templates"}, "meme_templates.yaml", file)
    out: dict[str, MemeTemplate] = {}
    for tid, raw in _text_keys(
        _mapping(data.get("templates"), "templates", file), "meme template", file
    ).items():
        raw = _mapping(raw, f"meme template '{tid}'", file)
        _check_keys(raw, {"lines", "hint", "fits"}, f"meme template '{tid}'", file)
        out[tid] = MemeTemplate(
            tid,
            int(raw.get("lines", 2)),
            str(raw.get("hint", "")),
            tuple(str(t) for t in raw.get("fits") or ()),
        )
    return out


_LANG_KEYS = {
    "extensions", "comment", "block", "func_start", "entry_points", "entry_paths",
    "import_style", "imports", "public", "branch", "skipped_test", "catch_all", "sleep",
    "regex_literal", "bit_ops", "meta", "commented_code", "thresholds", "def_patterns",
}  # fmt: skip


def load_languages(root: Path | None = None) -> dict:
    """config/languages.yaml as {"thresholds": {...}, "languages": {name: {...}}}."""
    import re

    root = project_root() if root is None else Path(root)
    file = root / "config" / "languages.yaml"
    data = _mapping(_read(file), "languages.yaml", file)
    _check_keys(data, {"languages", "thresholds"}, "languages.yaml", file)
    langs = _text_keys(_mapping(data.get("languages"), "languages", file), "language", file)
    for name, raw in langs.items():
        raw = _mapping(raw, f"language '{name}'", file)
        _check_keys(raw, _LANG_KEYS, f"language '{name}'", file)
        if not raw.get("extensions"):
            raise ConfigError(f"language '{name}' is missing 'extensions' ({file})")
        for key, val in raw.items():
            if key in ("extensions", "comment", "block", "import_style", "thresholds"):
                continue
            for pat in [val] if isinstance(val, str) else val:
                try:
                    re.compile(pat)
                except (re.error, TypeError) as e:
                    raise ConfigError(
                        f"bad pattern in language '{name}' {key}: {e} ({file})"
                    ) from e
    return {"thresholds": _mapping(data.get("thresholds"), "thresholds", file), "languages": langs}


_SCAN_KEYS = {"scan", "ignore", "kinds", "generated_markers", "noise"}


def load_scan_defaults(root: Path | None = None) -> dict:
    """config/scan_defaults.yaml: the file set of a repo that has no profile."""
    root = project_root() if root is None else Path(root)
    file = root / "config" / "scan_defaults.yaml"
    if not file.is_file():  # a test root without the file: use the shipped one
        file = Path(__file__).parents[2] / "config" / "scan_defaults.yaml"
    data = _mapping(_read(file, required=True), "scan_defaults.yaml", file)
    _check_keys(data, _SCAN_KEYS, "scan_defaults.yaml", file)
    return data


_FILE_TYPE_KEYS = {
    "highlight", "file_words", "source_extensions", "noise_basenames", "manifests",
    "ast_grep_probe", "why_words", "doc_extensions", "comment_prefixes",
}  # fmt: skip


def load_file_types(root: Path | None = None) -> dict:
    """config/file_types.yaml: extension tables, noise file names, manifest names."""
    root = project_root() if root is None else Path(root)
    file = root / "config" / "file_types.yaml"
    if not file.is_file():  # a test root without the file: use the shipped one
        file = Path(__file__).parents[2] / "config" / "file_types.yaml"
    data = _mapping(_read(file, required=True), "file_types.yaml", file)
    _check_keys(data, _FILE_TYPE_KEYS, "file_types.yaml", file)
    return data


def file_types() -> dict:
    """The shipped file types (cached; the project root when there is one)."""
    return _file_types_cached()


@cache
def _file_types_cached() -> dict:
    try:
        return load_file_types()
    except ConfigError:
        return load_file_types(Path(__file__).parents[2])


@cache
def language_extensions() -> frozenset[str]:
    """Every extension (with its dot) that config/languages.yaml or config/queries/ maps to a
    language."""
    from . import structure

    try:
        langs = load_languages()
    except ConfigError:
        langs = load_languages(Path(__file__).parents[2])
    out = {e for raw in langs["languages"].values() for e in raw["extensions"]}
    out |= set(structure._by_ext())
    return frozenset(out)


def source_extensions() -> frozenset[str]:
    """Extensions of source-like files: language extensions and `source_extensions`."""
    return language_extensions() | frozenset(file_types().get("source_extensions") or ())


def file_word_extensions() -> frozenset[str]:
    """Extensions (no dot) that make a word look like a file name in a claim."""
    exts = language_extensions() | set(file_types().get("highlight") or ())
    return frozenset(e.lstrip(".") for e in exts) | frozenset(file_types().get("file_words") or ())


def load_config(root: Path | None = None) -> Config:
    root = project_root() if root is None else Path(root).resolve()
    from .profiles import load_profiles

    repos, groups = _load_repos(root)
    defaults_file = root / "config" / "defaults.yaml"
    defaults = _mapping(_read(defaults_file), "defaults.yaml", defaults_file)
    return Config(
        root=root,
        repos=repos,
        groups=groups,
        settings=_load_settings(root),
        defaults=defaults,
        personas=_load_personas(root),
        mascots=_load_mascots(root),
        meme_templates=_load_meme_templates(root),
        languages=load_languages(root),
        profiles=load_profiles(root),
        scan_defaults=load_scan_defaults(root),
    )
