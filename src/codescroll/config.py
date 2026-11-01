"""Load CodeScroll configuration from the project's config/ directory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
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
    url: str | None = None  # web URL of the repo (GitHub); None means derive it from `origin`


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


@dataclass(frozen=True)
class AgentSettings:
    default_count: int = 10
    max_count: int = 20
    per_day_runs: int = 4
    packet_size: int = 2
    target_runway_days: int = 3
    min_burn_per_day: int = 10
    min_run_count: int = 8
    lead_cooldown_days: int = 30
    variant_min_reward: float = 0.6
    variant_after_days: int = 14
    variant_max_share: float = 0.2


@dataclass(frozen=True)
class AnalysisSettings:
    history_window_days: int = 720
    churn_windows_days: tuple[int, ...] = (30, 90, 365)
    blame_max_files: int = 50
    blame_max_bytes: int = 2000000
    todo_max_hits: int = 150


@dataclass(frozen=True)
class ResearchSettings:
    max_output_bytes: int = 200000
    max_read_lines: int = 300


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
class Settings:
    data_dir: Path
    server: ServerSettings
    agent: AgentSettings
    analysis: AnalysisSettings
    research: ResearchSettings
    render: RenderSettings = field(default_factory=RenderSettings)
    repos: ReposSettings = field(default_factory=ReposSettings)
    gc: GcSettings = field(default_factory=GcSettings)


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

    def repo(self, name: str) -> Repo:
        try:
            return self.repos[name]
        except KeyError:
            raise ConfigError(f"unknown repo: {name}") from None


def project_root(start: Path | None = None) -> Path:
    env = os.environ.get("CODESCROLL_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "config" / "repos.yaml").is_file():
            return d
    raise ConfigError("project root not found: no config/repos.yaml in any parent directory")


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


def _load_settings(root: Path) -> Settings:
    file = root / "config" / "settings.yaml"
    data = _mapping(_read(file), "settings", file)
    _check_keys(
        data,
        {"data_dir", "server", "agent", "analysis", "research", "render", "repos", "gc"},
        "settings",
        file,
    )
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
    )


def _load_repos(root: Path) -> tuple[dict[str, Repo], dict[str, Group]]:
    file = root / "config" / "repos.yaml"
    data = _mapping(_read(file, required=True), "repos.yaml", file)
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
        _check_keys(raw, {"path", "ref", "mascot", "group", "url"}, f"repo '{rname}'", file)
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
        )

    # repo-level group: keys add membership to the group
    for rname, repo in repos.items():
        if repo.group and rname not in groups[repo.group].repos:
            g = groups[repo.group]
            groups[repo.group] = Group(g.name, (*g.repos, rname), g.standalone)
    return repos, groups


def _load_personas(root: Path) -> dict[str, Persona]:
    file = root / "config" / "personas.yaml"
    data = _mapping(_read(file), "personas.yaml", file)
    _check_keys(data, {"personas"}, "personas.yaml", file)
    out: dict[str, Persona] = {}
    for handle, raw in _text_keys(
        _mapping(data.get("personas"), "personas", file), "persona", file
    ).items():
        raw = _mapping(raw, f"persona '{handle}'", file)
        _check_keys(raw, {"name", "voice"}, f"persona '{handle}'", file)
        for req in ("name", "voice"):
            if req not in raw:
                raise ConfigError(f"persona '{handle}' is missing '{req}' ({file})")
        out[handle] = Persona(handle, raw["name"], raw["voice"])
    return out


def _load_mascots(root: Path) -> dict[str, Mascot]:
    file = root / "config" / "mascots.yaml"
    data = _mapping(_read(file), "mascots.yaml", file)
    _check_keys(data, {"mascots"}, "mascots.yaml", file)
    out: dict[str, Mascot] = {}
    for name, raw in _text_keys(
        _mapping(data.get("mascots"), "mascots", file), "mascot", file
    ).items():
        raw = _mapping(raw, f"mascot '{name}'", file)
        _check_keys(raw, {"repo", "style", "seed"}, f"mascot '{name}'", file)
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


def load_config(root: Path | None = None) -> Config:
    root = project_root() if root is None else Path(root).resolve()
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
    )
