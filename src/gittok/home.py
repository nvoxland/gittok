"""`gittok init <dir>` and `gittok update`: make and refresh a GitTok directory.

A GitTok directory holds everything: the user's `local/`, `data/` and `repos/`, and the
files that tell an agent program how to run GitTok. Those files are in two kinds of unit.
`core_files` is for every agent program (`AGENTS.md`). Each entry of `HARNESSES` is for one
program (Claude Code or Codex: MCP configuration, skill discovery, session hooks).
Nothing here writes outside the directory.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from functools import cache
from pathlib import Path

import yaml

from .config import MARKER, ConfigError, is_clone, resolve_roots

SKILL_NAMES = ("gittok-generate", "gittok-steer", "gittok-profile-repo")
WORKER_NAMES = ("gittok-writer", "gittok-scout", "gittok-illustrator")  # the generate skill's
AGENT_FILES = tuple(f"{n}.md" for n in WORKER_NAMES)
TEMPLATES = Path(__file__).parent / "templates"
# The one agent-neutral source of the skills and workers. Each agent program gets full
# generated copies, with a last section on how it does the shared steps (harness/).
WORKFLOWS = Path(__file__).parent / "workflows"
IGNORED = {".DS_Store"}  # Finder makes it; a directory with only this file is empty
MARKER_HEAD = (
    "# `gittok init` wrote this file. It marks this directory as a GitTok directory.\n"
    "# `gittok update` rewrites it. Do not edit or delete it.\n"
)

LAN_LINES = (
    "Phone access is on: while a session runs, the feed is served to your local network over "
    "plain HTTP. A device gets nothing until it pairs: tap 'Pair with a code' on it and tell "
    "your coding agent the code that it shows. Use it on a network you trust.",
    "To turn it off, ask your coding agent to turn off phone access.",
)


class InitError(Exception):
    """`init` or `update` cannot run on this path. The message is one line for the user."""


def installed_version() -> str:
    """The installed package version (from the package metadata)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("gittok")
    except PackageNotFoundError:  # run from a source tree that is not installed
        return "unknown"


def server_dir(port: int) -> str | None:
    """The GitTok directory of the feed server on this computer's `port`, if one answers."""
    import httpx

    try:
        data = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2.0).json()
    except (httpx.HTTPError, ValueError):
        return None
    return _checked_dir(data.get("dir") if isinstance(data, dict) else None)


def _checked_dir(found: object) -> str | None:
    """`found` when it is the path of a GitTok directory or a clone on this computer, else
    None. Whatever answers on the port wrote this text, and it goes into text that an agent
    reads: it must be a short absolute path with no control character."""
    if not isinstance(found, str) or not 0 < len(found) <= 512:
        return None
    if not found.isprintable() or not found.startswith("/"):
        return None
    path = Path(found)
    if not path.is_dir() or not ((path / MARKER).is_file() or is_clone(path)):
        return None
    return found


def cli_command(clone: bool) -> str:
    """How a session runs the command line: through uv in a clone, the tool elsewhere."""
    return "uv run --quiet gittok" if clone else "gittok"


def feed_watch_command(clone: bool) -> str:
    """The exact command of the feed watch. The permission entry in the settings names it."""
    return f"{cli_command(clone)} feed-watch"


def core_files() -> dict[str, bytes]:
    """The owned files that every agent program reads: path in the directory -> content.

    `init` also writes the marker, `.gitignore` and `local/repos.yaml`; those are not here,
    because `update` handles the marker itself and never touches the other two."""
    return {"AGENTS.md": (TEMPLATES / "AGENTS.md").read_bytes()}


_FRONT = re.compile(r"\A---[ \t]*\n(.*?)^---[ \t]*$\n?", re.DOTALL | re.MULTILINE)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """(frontmatter, body) of a text that starts with a `---` delimited YAML block. The
    delimiters are whole lines, so a `---` rule or the text `---` in the body is kept."""
    m = _FRONT.match(text)
    if m is None:
        raise ValueError("no frontmatter: the text must start with a --- line")
    return yaml.safe_load(m.group(1)), text[m.end():].lstrip("\n")


@cache
def _source_cached(kind: str, name: str) -> tuple[str, str]:
    meta, body = split_frontmatter((WORKFLOWS / kind / f"{name}.md").read_text())
    return yaml.safe_dump(meta, sort_keys=False, width=100000, allow_unicode=True), body


def _source(kind: str, name: str) -> tuple[dict, str]:
    """The frontmatter and body of one neutral skill or worker source (read once)."""
    head, body = _source_cached(kind, name)
    return yaml.safe_load(head), body


def _document(meta: dict, *parts: str) -> bytes:
    head = yaml.safe_dump(meta, sort_keys=False, width=100000, allow_unicode=True)
    return ("---\n" + head + "---\n\n" + "\n".join(p.rstrip("\n") + "\n" for p in parts)).encode()


def _harness_section(program: str) -> str:
    return (WORKFLOWS / "harness" / f"{program}.md").read_text()


# The `model:` of a generated Claude Code skill is fixed when the files are generated: it is
# not read from `agent.models`, which the user can change later. Workers say `inherit`
# (the session's model); the driver passes the model of the packet when it starts a worker.
SKILL_MODELS = {"light": "haiku", "standard": "sonnet"}


def _claude_model(tier: str) -> str:
    return SKILL_MODELS[tier]


def claude_code_files() -> dict[str, bytes]:
    """The owned files that only Claude Code reads: the MCP entry, a `CLAUDE.md` that points
    to `AGENTS.md`, the session settings, and the skills and agents (generated)."""
    out = {
        ".mcp.json": (TEMPLATES / "mcp.json").read_bytes(),
        "CLAUDE.md": (TEMPLATES / "CLAUDE.md").read_bytes(),
        ".claude/settings.json": (TEMPLATES / "settings.json").read_bytes(),
    }
    section = _harness_section("claude")
    for name in SKILL_NAMES:
        meta, body = _source("skills", name)
        head = {"name": name, "description": meta["description"],
                "model": _claude_model(meta["tier"])}
        out[f".claude/skills/{name}/SKILL.md"] = _document(head, body, section)
    for name in WORKER_NAMES:
        meta, body = _source("workers", name)
        head = {"name": name, "description": meta["description"],
                "tools": ", ".join(f"mcp__gittok__{t}" for t in meta["tools"]),
                "model": "inherit"}
        out[f".claude/agents/{name}.md"] = _document(head, body)
    return out


def codex_files() -> dict[str, bytes]:
    """The owned files that only Codex reads: its MCP entry and hooks, its runtime notes,
    and the skills and workers (generated from the same sources as Claude Code's)."""
    settings = json.loads((TEMPLATES / "settings.json").read_text())
    out = {
        ".codex/config.toml": (TEMPLATES / "codex.toml").read_bytes(),
        ".codex/hooks.json": (json.dumps({"hooks": settings["hooks"]}, indent=2) + "\n").encode(),
        ".agents/GITTOK.md": (TEMPLATES / "codex.md").read_bytes(),
    }
    section = _harness_section("codex")
    for name in SKILL_NAMES:
        meta, body = _source("skills", name)
        head = {"name": name, "description": meta["description"]}
        out[f".agents/skills/{name}/SKILL.md"] = _document(head, body, section)
    for name in WORKER_NAMES:
        meta, body = _source("workers", name)
        head = {"name": name, "description": meta["description"], "tools": meta["tools"],
                "tier": meta["tier"]}
        out[f".agents/workers/{name}.md"] = _document(head, body)
    return out


def write_clone_files(root: Path) -> list[str]:
    """Write the generated skills and workers into a clone (they are committed there)."""
    written = []
    for files in (claude_code_files(), codex_files()):
        for rel, data in files.items():
            if rel.startswith((".claude/skills/", ".claude/agents/", ".agents/")):
                path = root / rel
                if not path.is_file() or path.read_bytes() != data:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    written.append(rel)
    return written


# One unit of files for each agent program. Files for another program go in a new unit here.
HARNESSES = {"Claude Code": claude_code_files, "Codex": codex_files}


def owned_files() -> dict[str, bytes]:
    """The files that `init` writes and `update` rewrites: path in the directory -> content."""
    out = core_files()
    for files in HARNESSES.values():
        out.update(files())
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_marker(home: Path, version: str, files: dict[str, bytes]) -> None:
    body = {"version": version, "files": {rel: _sha(data) for rel, data in sorted(files.items())}}
    (home / MARKER).write_text(MARKER_HEAD + yaml.safe_dump(body, sort_keys=False))


def read_marker(home: Path) -> dict | None:
    """The marker of a GitTok directory, or None when `home` is not one."""
    try:
        data = yaml.safe_load((home / MARKER).read_text())
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else {}


def recorded_version(home: Path) -> str | None:
    marker = read_marker(home)
    return str(marker["version"]) if marker and marker.get("version") is not None else None


def _check_target(target: Path) -> None:
    """Raise InitError unless `target` is free for a new GitTok directory."""
    for d in (target, *target.parents):
        if d.exists() and not d.is_dir():
            raise InitError(f"{d} is a file. Give `gittok init` a new or an empty directory.")
    if (target / MARKER).is_file():
        raise InitError(
            f"{target} is already a GitTok directory. To refresh its files, run "
            f"`gittok update {target}`."
        )
    for d in (target, *target.parents):
        if (d / MARKER).is_file():
            raise InitError(f"{target} is inside the GitTok directory {d}. Use another path.")
        if is_clone(d):
            raise InitError(
                f"{target} is inside the GitTok source clone {d}. A clone is its own GitTok "
                "directory. Use a path outside it."
            )
    if target.is_dir() and any(p.name not in IGNORED for p in target.iterdir()):
        raise InitError(
            f"{target} is not empty. `gittok init` needs a new or an empty directory, and "
            "it changed nothing."
        )


def init(target: Path, version: str) -> list[str]:
    """Make the GitTok directory `target`. Return the lines to print."""
    target = Path(target).expanduser().resolve()
    _check_target(target)
    files = owned_files()
    target.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        _write(target / rel, data)
    _write(target / ".gitignore", (TEMPLATES / "gitignore").read_bytes())
    _write(target / "local" / "repos.yaml", (TEMPLATES / "repos.yaml").read_bytes())
    _write_marker(target, version, files)
    return [
        f"Made the GitTok directory {target}:",
        f"  {MARKER}         marks the directory (gittok {version})",
        "  AGENTS.md           tells your coding agent what this directory is",
        "  local/repos.yaml    your repo list (empty now)",
        "  .gitignore          for data/ and repos/, if you put the directory under git",
        "For Claude Code:",
        "  .mcp.json           starts `gittok mcp --ui` when Claude Code starts here",
        "  CLAUDE.md           points to AGENTS.md",
        "  .claude/skills/     " + ", ".join(SKILL_NAMES),
        "  .claude/agents/     " + ", ".join(WORKER_NAMES),
        "  .claude/settings.json   the session hooks that keep the feed full",
        "For Codex:",
        "  .codex/config.toml  starts the same MCP server (stdio)",
        "  .codex/hooks.json   the same session hints (review with /hooks)",
        "  .agents/skills/     " + ", ".join(SKILL_NAMES),
        "  .agents/workers/    " + ", ".join(WORKER_NAMES),
        "  .agents/GITTOK.md   notes for Codex sessions (connection, startup hints, feed watch)",
        "Your cards and settings will be in this directory (data/, local/, repos/). "
        "Nothing is written outside it.",
        "",
        "Next: start your coding agent in the directory. With Claude Code:",
        f"  cd {target}",
        "  claude",
        "Claude Code asks one time to approve the MCP server `gittok` of this directory. "
        "Approve it. Then ask the agent to add a repo.",
        "Or run `codex` here, trust the project configuration and review /hooks. "
        "Ask Codex to add a repo; $gittok-generate makes cards on demand.",
        "GitTok runs only while an agent session is open in this directory.",
        "",
        *LAN_LINES,
    ]


def _free_backup(path: Path) -> Path:
    """`<name>.bak`, or `<name>.bak.1`, `.bak.2`, ... : the first name that is free."""
    backup = path.with_name(path.name + ".bak")
    n = 0
    while backup.exists():
        n += 1
        backup = path.with_name(f"{path.name}.bak.{n}")
    return backup


def update(home: Path, version: str) -> list[str]:
    """Rewrite the files that `init` owns in the GitTok directory `home`. Return the lines.

    A file that differs from what the last `init` or `update` wrote was edited by the user:
    its old content is saved as `<name>.bak` first (`.bak.1`, ... when that exists: a backup
    is never overwritten). `local/`, `data/` and `repos/` are never touched."""
    home = Path(home).expanduser().resolve()
    marker = read_marker(home)
    if marker is None:
        raise InitError(
            f"{home} is not a GitTok directory (no {MARKER}). Make one with `gittok init <dir>`."
        )
    recorded = marker.get("files") if isinstance(marker.get("files"), dict) else {}
    old_version = str(marker.get("version", "unknown"))
    files = owned_files()
    lines: list[str] = []
    for rel, data in files.items():
        path = home / rel
        if not path.is_file():
            _write(path, data)
            lines.append(f"added {rel}")
            continue
        current = path.read_bytes()
        if current == data:
            continue
        if recorded.get(rel) == _sha(current):
            lines.append(f"updated {rel}")
        else:
            backup = _free_backup(path)
            backup.write_bytes(current)
            old = rel[: len(rel) - len(path.name)] + backup.name
            lines.append(f"updated {rel}: you edited it, the old copy is {old}")
        path.write_bytes(data)
    for rel in sorted(set(recorded) - set(files)):  # shipped by an older version only
        path = home / rel
        if not path.is_file():
            continue
        if recorded[rel] == _sha(path.read_bytes()):
            path.unlink()
            lines.append(f"removed {rel} (this version does not have it)")
        else:
            lines.append(f"kept {rel}: this version does not have it, and you edited it")
    _write_marker(home, version, files)
    if old_version != version:
        lines.append(f"version: {old_version} -> {version}")
    if not lines:
        return [f"{home} is up to date (gittok {version})."]
    return [
        f"Updated the GitTok directory {home}:",
        *(f"  {ln}" for ln in lines),
        "Start a new agent session in the directory to load the new files.",
    ]


def version_hint(home: Path, installed: str) -> str | None:
    """One line for the session when the directory was written by another GitTok version."""
    recorded = recorded_version(home)
    if recorded is None or recorded == installed:
        return None
    return (
        f"GitTok: this directory has the files of gittok {recorded}, and the installed tool "
        f"is gittok {installed}. Tell the user, and offer to run `gittok update` with Bash "
        "(it writes the new skills, agents and settings; an edited file is kept as "
        "<name>.bak). After it, the user starts a new session."
    )


def _clone_root() -> Path:
    return resolve_roots()[1]


def main() -> int:
    """Regenerate the committed skills and workers of a clone. 1 when this is not a clone."""
    try:
        root = _clone_root()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not is_clone(root):
        print(f"error: {root} is not a source clone (no config/settings.yaml). Run this in "
              "a clone of gittok.", file=sys.stderr)
        return 1
    for rel in write_clone_files(root):
        print("wrote", rel)
    return 0


if __name__ == "__main__":  # in a clone: `uv run python -m gittok.home`
    sys.exit(main())
