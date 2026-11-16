"""Load GitTok configuration from the project's config/ directory."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


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
    remote: str | None = None  # set by `repos add <url>`: GitTok cloned it into <home>/repos


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
    # Worker model per agent program and tier; a missing tier: the session's model.
    models: dict = field(default_factory=lambda: {
        "claude": {"light": "haiku", "standard": "sonnet"}, "codex": {}})


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
    git_timeout_s: float = 120  # one read-only git call is stopped after this long
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
    image_backend: str = "auto"  # auto: Codex agent, Claude Python; missing mflux: agent
    max_illustrations_per_run: int = 6
    # Where `gittok memes --prefetch` downloads meme templates and fonts from (memes.py).
    meme_source: str = "https://raw.githubusercontent.com/jacebrowning/memegen/main"
    mflux_model: str = "z-image-turbo"  # the model family (mflux's base model name)
    # The pre-quantized model GitTok downloads, pinned to one revision (image_model.py).
    mflux_repo: str = "filipstrand/Z-Image-Turbo-mflux-4bit"
    mflux_revision: str = "b3a8f31115a11f2f9e2fa0bfbc8d78dcc3e6568b"
    mflux_auto_download: bool = True  # the feed server downloads it when the renderer is installed
    mflux_path: str = ""  # a saved model folder; empty = <data_dir>/models/<repo name>
    mflux_steps: int = 9
    mflux_low_ram: bool = True
    mflux_timeout_s: float = 120.0  # one image, once the model is loaded
    mflux_load_timeout_s: float = 600.0  # loading the model, once per batch
    mflux_batch_idle_s: float = 10.0
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
    port: int = 7313
    lan: bool = True  # serve the feed to the LAN (paired devices only); false: loopback only
    # Extra Host names the server answers to (its own names and addresses are always allowed).
    allowed_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReposSettings:
    # An optional limit for the add_repo MCP tool. Empty means no limit.
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


def unknown_repo(repos, name) -> str:
    """The one error text for a repo name that is not configured (every tool and command)."""
    known = ", ".join(sorted(repos)) or "(none)"
    return f"unknown repo: {name}. Known repos: {known}"


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
    shared: Path | None = None  # where config/, web/ and claude/ live; None means `root`
    # Problems that did not stop the load: unknown settings and reward keys (`gittok health`).
    warnings: tuple[str, ...] = ()

    def shared_path(self, *parts: str) -> Path:
        """A path under the shared root (the clone, or the bundle in an installed app)."""
        return (self.shared or self.root).joinpath(*parts)

    def repo(self, name: str) -> Repo:
        try:
            return self.repos[name]
        except KeyError:
            raise ConfigError(unknown_repo(self.repos, name)) from None

    def mascot_for(self, repo: str) -> Mascot | None:
        """The mascot that cards of `repo` use: the one its entry names, else the first whose
        own `repo` is this repo. None when it has none."""
        r = self.repos.get(repo)
        if r is not None and r.mascot in self.mascots:
            return self.mascots[r.mascot]
        return next((m for m in self.mascots.values() if m.repo == repo), None)

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


def bundle_dir() -> Path:
    """The shared files bundled in the installed package (absent in a clone)."""
    return Path(__file__).parent / "_bundled"


def shipped_root() -> Path:
    """Where the shipped `config/` lives: the bundle when installed, else the clone."""
    b = bundle_dir()
    return b if (b / "config").is_dir() else Path(__file__).parents[2]


HARNESS_NAMES = ("claude", "codex")
TIERS = ("light", "standard")  # the work a worker does: rating or simple formats, or the rest


def harness() -> str:
    """The agent program of this session: `codex` when its MCP launch says so, else `claude`."""
    return "codex" if os.environ.get("GITTOK_AGENT") == "codex" else "claude"


def worker_models(cfg) -> dict[str, str | None]:
    """The model of each worker tier for this session's agent program (None: its own model)."""
    mapping = cfg.settings.agent.models.get(harness()) or {}
    return {tier: mapping.get(tier) or None for tier in TIERS}


MARKER = "gittok.yaml"  # written by `gittok init`; a directory that has it is a GitTok directory
NO_ROOT = (
    "not inside a GitTok directory. Make one with `gittok init <dir>` and start Claude Code "
    "there, or start Codex there."
)


def is_clone(root: Path) -> bool:
    """True for a source clone (it has the shipped `config/`), false for a GitTok directory."""
    return (root / "config" / "settings.yaml").is_file()


def _roots_at(d: Path) -> tuple[Path, Path] | None:
    if (d / MARKER).is_file():
        return shipped_root(), d
    if is_clone(d):
        return d, d
    return None


def resolve_roots(start: Path | None = None) -> tuple[Path, Path]:
    """(shared root, home). A GitTok directory: the shipped files and the directory. A source
    clone: both are the clone.

    The home is found by walking up from `start` (default: the current directory) to a
    directory with the marker of `gittok init`, or to a clone. `GITTOK_ROOT` names one of
    the two directly. Nothing is created here.
    """
    env = os.environ.get("GITTOK_ROOT")
    if env:
        r = Path(env).expanduser().resolve()
        found = _roots_at(r)
        if found is None:
            raise ConfigError(f"GITTOK_ROOT={env} is not a GitTok directory (no {MARKER})")
        return found
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        found = _roots_at(d)
        if found is not None:
            return found
    raise ConfigError(NO_ROOT)


def shared_root(start: Path | None = None) -> Path:
    return resolve_roots(start)[0]


def _read(path: Path, required: bool = False) -> Any:
    if not path.is_file():
        if required:
            raise ConfigError(f"missing config file: {path}")
        return None
    try:
        return yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {' '.join(str(e).split())}") from e


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


_CLAUDE_ALIASES = ("haiku", "sonnet", "opus", "inherit")


def _models(models: Any, what: str, file: Path) -> dict:
    """`agent.models`, checked: a mapping of agent program -> a mapping of tier -> model."""
    if models is None:
        return {}
    if not isinstance(models, dict) or not set(models) <= set(HARNESS_NAMES):
        raise ConfigError(f"{what}.models has a key per agent program: claude or codex ({file})")
    out = {}
    for name, tiers in models.items():
        if tiers is None:
            tiers = {}
        if not isinstance(tiers, dict) or not set(tiers) <= set(TIERS):
            raise ConfigError(f"{what}.models.{name} has a key per tier: light or standard "
                              f"({file})")
        for tier, m in tiers.items():
            if m is not None and not isinstance(m, str):
                raise ConfigError(f"{what}.models.{name}.{tier}: a model name is text ({file})")
            if name == "claude" and m and m not in _CLAUDE_ALIASES and not m.startswith("claude-"):
                raise ConfigError(
                    f"{what}.models.claude.{tier}: '{m}' is not a Claude model. Use haiku, "
                    f"sonnet, opus, inherit, or a full id such as claude-sonnet-4-5 ({file})")
        out[name] = tiers
    return out


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# Where the default range of a number is not "0 or more": (least, most).
_RANGES: dict[str, tuple[float, float]] = {
    "packet_size": (1, 5),
    "port": (1, 65535),
    "min_spot_the_bug_per_run": (0, 1), "variant_max_share": (0, 1), "intro_share": (0, 1),
    "variant_min_reward": (0, 1),
    **dict.fromkeys(
        ("default_count", "max_count", "target_runway_days", "min_burn_per_day", "min_run_count",
         "scout_max", "scout_batch", "max_read_lines", "max_output_bytes", "image_width",
         "image_height", "mflux_steps", "max_illustrations_per_run", "worker_interval_s",
         "interval_s", "history_window_days", "log_max_kb", "max_hits", "max_ms",
         "candidates_per_tag"),
        (1, math.inf)),
}  # fmt: skip


def _check_values(cls: type, kwargs: dict, what: str, file: Path) -> None:
    """Type and range of each plain value, from the type of its default: a number is a number
    (not a bool, not text) and in range, a flag is true or false, text is text. A bad value is
    a one-line ConfigError here, not a crash in the code that uses it later."""
    for f in fields(cls):
        if f.name not in kwargs:
            continue
        v, default = kwargs[f.name], f.default
        if v is None and not isinstance(default, tuple | dict):
            del kwargs[f.name]  # `key:` with no value means the default
            continue
        where = f"{what}.{f.name}"
        if isinstance(default, bool):
            if not isinstance(v, bool):
                raise ConfigError(f"{where} must be true or false ({file})")
        elif isinstance(default, str):
            if not isinstance(v, str):
                raise ConfigError(f"{where} must be text ({file})")
        elif isinstance(default, int | float):
            ok = (_is_int(v) if isinstance(default, int)
                  else isinstance(v, int | float) and not isinstance(v, bool))
            if not ok or (isinstance(v, float) and not math.isfinite(v)):
                kind = "a whole number" if isinstance(default, int) else "a number"
                raise ConfigError(f"{where} must be {kind} ({file})")
            lo, hi = _RANGES.get(f.name, (0, math.inf))
            if not lo <= v <= hi:
                rng = f"{lo:g} or more" if hi == math.inf else f"{lo:g} to {hi:g}"
                raise ConfigError(f"{where} must be {rng}, not {v} ({file})")


def _section(cls: type, data: Any, what: str, file: Path) -> Any:
    data = _mapping(data, what, file)
    _check_keys(data, {f.name for f in fields(cls)}, what, file)
    kwargs = dict(data)
    if "git_identities" in kwargs:
        ids = kwargs["git_identities"] or []
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ConfigError(f"{what}.git_identities must be a list of text ({file})")
        kwargs["git_identities"] = tuple(ids)
    if cls is AgentSettings and "models" in kwargs:
        kwargs["models"] = _models(kwargs["models"], what, file)
    if "churn_windows_days" in kwargs:
        days = kwargs["churn_windows_days"]
        if (not isinstance(days, list | tuple) or not days
                or not all(_is_int(d) and d > 0 for d in days)):
            raise ConfigError(f"{what}.churn_windows_days must be a list of days above 0 ({file})")
        kwargs["churn_windows_days"] = tuple(days)
    _check_values(cls, kwargs, what, file)
    if "git_timeout_s" in kwargs:
        t = kwargs["git_timeout_s"]
        if isinstance(t, bool) or not isinstance(t, int | float) or t <= 0:
            raise ConfigError(f"{what}.git_timeout_s must be a number of seconds above 0 ({file})")
    if cls is RenderSettings:
        if kwargs.get("image_backend", "auto") not in ("auto", "agent", "local"):
            raise ConfigError(f"{what}.image_backend must be auto, agent or local ({file})")
        for name, default in (
            ("mflux_timeout_s", 120), ("mflux_load_timeout_s", 600), ("mflux_batch_idle_s", 10)
        ):
            seconds = kwargs.get(name, default)
            if (isinstance(seconds, bool) or not isinstance(seconds, int | float)
                    or not math.isfinite(seconds) or seconds <= 0):
                raise ConfigError(f"{what}.{name} must be finite seconds above 0 ({file})")
        for name in ("mflux_low_ram", "mflux_auto_download"):
            if not isinstance(kwargs.get(name, True), bool):
                raise ConfigError(f"{what}.{name} must be true or false ({file})")
    if cls is ServerSettings:
        if not isinstance(kwargs.get("lan", True), bool):
            raise ConfigError(f"{what}.lan must be true or false ({file})")
        hosts = kwargs.get("allowed_hosts") or []
        if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
            raise ConfigError(f"{what}.allowed_hosts must be a list of host names ({file})")
        kwargs["allowed_hosts"] = tuple(hosts)
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{what} is not valid: {' '.join(str(e).split())} ({file})") from e


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


_SECTIONS: dict[str, type] = {
    "server": ServerSettings,
    "agent": AgentSettings,
    "analysis": AnalysisSettings,
    "research": ResearchSettings,
    "render": RenderSettings,
    "repos": ReposSettings,
    "gc": GcSettings,
    "user": UserSettings,
    "profiles": ProfilesSettings,
}
_warned: set[str] = set()  # unknown-key warnings already logged by this process


def _drop_unknown(data: dict, file: Path) -> tuple[dict, list[str]]:
    """`data` without the settings keys this code does not know, and one warning for each.

    An unknown key is not an error: a process that started before an upgrade (the MCP
    server does not reload code) must still load a newer settings file. `gittok health`
    prints the warnings, so a typo stays visible.
    """
    where = "/".join(file.parts[-2:])
    out: dict = {}
    unknown: list[str] = []
    for key, val in data.items():
        if key not in _SETTINGS_KEYS:
            unknown.append(str(key))
            continue
        cls = _SECTIONS.get(key)
        if cls is not None and isinstance(val, dict):
            names = {f.name for f in fields(cls)}
            unknown += [f"{key}.{k}" for k in val if k not in names]
            val = {k: v for k, v in val.items() if k in names}
        out[key] = val
    warnings = [f"unknown settings key '{k}' in {where} (ignored)" for k in unknown]
    for w in warnings:
        if f"{file}:{w}" not in _warned:
            _warned.add(f"{file}:{w}")
            log.warning("%s", w)
    return out, warnings


def merge_settings(base: dict, local: dict | None) -> dict:
    """The settings of `local` over `base`: a section merges key by key, a null is ignored,
    and `agent.models` merges per agent program and per tier, so that a local Codex tier does
    not drop the shipped Claude tiers."""
    merged = dict(base)
    for key, val in (local or {}).items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
            if key == "agent":
                merged[key]["models"] = _merge_models(base.get("agent"), val)
        elif val is not None:
            merged[key] = val
    return merged


def _merge_models(base_agent: dict | None, local_agent: dict) -> Any:
    base = (base_agent or {}).get("models")
    local = local_agent.get("models")
    if not isinstance(base, dict) or not isinstance(local, dict):
        return local if "models" in local_agent else base
    out = dict(base)
    for harness_name, tiers in local.items():
        mine = out.get(harness_name)
        out[harness_name] = (
            {**mine, **tiers} if isinstance(mine, dict) and isinstance(tiers, dict) else tiers
        )
    return out


def _load_settings(root: Path, shared: Path | None = None) -> tuple[Settings, tuple[str, ...]]:
    """config/settings.yaml, with the optional local/settings.yaml merged over it, and the
    warnings for keys that were ignored.

    Top-level keys replace; mapping sections merge key by key. Each file is checked on its
    own first, so a bad value names the file that holds it.
    """
    base_file = (shared or root) / "config" / "settings.yaml"
    local_file = root / "local" / "settings.yaml"
    base, base_warn = _drop_unknown(_mapping(_read(base_file), "settings", base_file), base_file)
    local, local_warn = _drop_unknown(
        _mapping(_read(local_file), "settings", local_file), local_file
    )
    _build_settings(base, root, base_file)
    if local:
        _build_settings(local, root, local_file)
    merged = merge_settings(base, local)
    settings = _build_settings(merged, root, local_file if local else base_file)
    return settings, (*base_warn, *local_warn)


def _build_settings(data: dict, root: Path, file: Path) -> Settings:
    _check_keys(data, _SETTINGS_KEYS, "settings", file)
    raw_dir = data.get("data_dir")
    if raw_dir is not None and not isinstance(raw_dir, str):
        raise ConfigError(f"settings.data_dir must be a path ({file})")
    data_dir = Path(raw_dir or "data").expanduser()
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
            raw,
            {"path", "ref", "mascot", "group", "url", "fetch", "remote"},
            f"repo '{rname}'",
            file,
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
            remote=raw.get("remote"),
            fetch=_as_bool(raw.get("fetch", False), f"repo '{rname}' fetch", file),
        )

    # repo-level group: keys add membership to the group
    for rname, repo in repos.items():
        if repo.group and rname not in groups[repo.group].repos:
            g = groups[repo.group]
            groups[repo.group] = Group(g.name, (*g.repos, rname), g.standalone)
    return repos, groups


def _personas(data: dict) -> dict[str, Persona]:
    return {
        handle: Persona(handle, raw["name"], raw["voice"], raw.get("bio"))
        for handle, raw in (data.get("personas") or {}).items()
    }


def _load_mascots(root: Path) -> dict[str, Mascot]:
    """local/mascots.yaml. Nothing is shipped: a mascot belongs to the user's own repo."""
    file = root / "local" / "mascots.yaml"
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


def _meme_templates(data: dict) -> dict[str, MemeTemplate]:
    return {
        tid: MemeTemplate(
            tid,
            int((raw or {}).get("lines", 2)),
            str((raw or {}).get("hint", "")),
            tuple(str(t) for t in (raw or {}).get("fits") or ()),
        )
        for tid, raw in (data.get("templates") or {}).items()
    }


_LANG_KEYS = {
    "extensions", "comment", "block", "func_start", "entry_points", "entry_paths",
    "import_style", "imports", "public", "branch", "skipped_test", "catch_all", "sleep",
    "regex_literal", "bit_ops", "meta", "commented_code", "thresholds", "def_patterns",
    "magic_exempt", "big_literal_start", "self_call", "comment_also", "param_open",
    "param_skip", "nesting_skip", "directive_prefixes", "comment_strip",
}  # fmt: skip
# Keys whose values are plain text or lists of text, not regexes.
_LANG_TEXT_KEYS = {
    "extensions", "comment", "block", "import_style", "thresholds", "comment_also",
    "param_open", "param_skip", "nesting_skip", "directive_prefixes", "comment_strip",
}  # fmt: skip


def _overlaid(name: str, root: Path | None, home: Path | None) -> dict:
    """The data of one overlaid file: for the active roots, or for the roots given."""
    from . import overlay

    if root is None and home is None:
        return overlay.data(name)
    return overlay.load(name, root, home).data


def load_languages(root: Path | None = None, home: Path | None = None) -> dict:
    """config/languages.yaml, with local/languages.yaml merged over it, as
    {"thresholds": {...}, "shared": {...}, "languages": {...}}.

    `shared` holds line shapes for every language; a language may set the same keys."""
    data = _overlaid("languages", root, home)
    return {
        "thresholds": data.get("thresholds") or {},
        "shared": data.get("shared") or {},
        "languages": data.get("languages") or {},
    }


_SCAN_KEYS = {"scan", "ignore", "kinds", "generated_markers", "noise"}


def load_scan_defaults(root: Path | None = None, home: Path | None = None) -> dict:
    """config/scan_defaults.yaml with local/scan_defaults.yaml merged over it: the file set of
    a repo that has no profile."""
    return _overlaid("scan_defaults", root, home)


_FILE_TYPE_KEYS = {
    "highlight", "file_words", "source_extensions", "noise_basenames", "manifests",
    "ast_grep_probe", "why_words", "doc_extensions", "comment_prefixes", "todo_comment",
    "two_meanings",
}  # fmt: skip


def load_file_types(root: Path | None = None, home: Path | None = None) -> dict:
    """config/file_types.yaml with local/file_types.yaml merged over it: extension tables,
    noise file names, manifest names."""
    return _overlaid("file_types", root, home)


def file_types() -> dict:
    """The file types of the active GitTok directory (shipped, with its local file merged)."""
    from . import overlay

    return overlay.data("file_types")


def language_extensions() -> frozenset[str]:
    """Every extension (with its dot) that languages.yaml or queries/languages.yaml maps to a
    language."""
    from . import overlay

    def build(langs: dict, queries: dict) -> frozenset[str]:
        out = {e for raw in (langs.get("languages") or {}).values() for e in raw["extensions"]}
        for raw in (queries.get("languages") or {}).values():
            out |= set(raw.get("extensions") or ())
        return frozenset(out)

    return overlay.derived(("languages", "queries"), "extensions", build)


def language_by_extension() -> dict[str, str]:
    """Extension (with its dot) -> language name, from languages.yaml, then the tags-query
    languages of queries/languages.yaml for extensions that languages.yaml does not map."""
    from . import overlay

    def build(langs: dict, queries: dict) -> dict[str, str]:
        out: dict[str, str] = {}
        for name, raw in (queries.get("languages") or {}).items():
            out.update(dict.fromkeys(raw.get("extensions") or (), name))
        for name, raw in (langs.get("languages") or {}).items():
            out.update(dict.fromkeys(raw["extensions"], name))
        return out

    return overlay.derived(("languages", "queries"), "language_by_extension", build)


def language_of(path: str) -> str | None:
    """The language of a file from its extension, or None."""
    dot = path.rfind(".")
    if dot <= path.rfind("/"):
        return None
    return language_by_extension().get(path[dot:].lower())


def source_extensions() -> frozenset[str]:
    """Extensions of source-like files: language extensions and `source_extensions`."""
    return language_extensions() | frozenset(file_types().get("source_extensions") or ())


def file_word_extensions() -> frozenset[str]:
    """Extensions (no dot) that make a word look like a file name in a claim."""
    exts = language_extensions() | set(file_types().get("highlight") or ())
    return frozenset(e.lstrip(".") for e in exts) | frozenset(file_types().get("file_words") or ())


# Files whose warnings and errors `load_config` reports, besides the ones it puts in the Config.
_CHECKED = ("file_types", "queries", "claims", "secrets")


def load_config(
    root: Path | None = None, shared: Path | None = None, activate: bool = True
) -> Config:
    """Load all config. `root` is the home (`local/`, data); `shared` holds `config/`.

    With no `root`, both come from `resolve_roots()`. With a `root` alone, shared is the root.
    Every shipped file is read with its `local/` file merged over it (overlay.py). `activate`
    makes these roots the ones that readers without a Config use (the secret detector, the
    file type tables, the queries).
    """
    if root is None:
        shared_dir, root = resolve_roots()
        shared = shared or shared_dir
    else:
        root = Path(root).resolve()
        shared = Path(shared).resolve() if shared else root
    import copy

    from . import gitq, overlay
    from .profiles import load_profiles

    if activate:
        # First, so that the home is known also when a file below is broken: `check_config`
        # then reports on this directory, and the readers fall back to the shipped file.
        overlay.activate(shared, root)
    repos, groups = _load_repos(root)
    settings, warnings = _load_settings(root, shared)
    files = {
        name: overlay.load(name, shared, root)
        for name in (
            "defaults",
            "personas",
            "meme_templates",
            "languages",
            "scan_defaults",
            "reward",
            *_CHECKED,
        )  # fmt: skip
    }
    for ld in files.values():
        warnings += ld.warnings
    cfg = Config(
        root=root,
        shared=shared,
        repos=repos,
        groups=groups,
        settings=settings,
        warnings=warnings,
        defaults=copy.deepcopy(files["defaults"].data),
        personas=_personas(files["personas"].data),
        mascots=_load_mascots(root),
        meme_templates=_meme_templates(files["meme_templates"].data),
        languages=copy.deepcopy(
            {
                "thresholds": files["languages"].data.get("thresholds") or {},
                "shared": files["languages"].data.get("shared") or {},
                "languages": files["languages"].data.get("languages") or {},
            }
        ),
        profiles=load_profiles(root),
        scan_defaults=copy.deepcopy(files["scan_defaults"].data),
    )
    if activate:
        gitq.set_timeout(settings.analysis.git_timeout_s)  # gitq takes paths, not a config
    return cfg
