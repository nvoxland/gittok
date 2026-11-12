"""`blamescroll install`: user-level MCP entry, skills, and a LaunchAgent for `serve`.

Dry run by default. Every side effect goes through `Env` (home dir, command runner,
PATH lookup), so tests never touch the real home directory.
"""

from __future__ import annotations

import difflib
import plistlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import claude_dir

SKILL_NAMES = ("blamescroll-generate", "blamescroll-steer", "blamescroll-profile-repo")
AGENT_FILES = (
    "blamescroll-writer.md",
    "blamescroll-scout.md",
)  # subagent types the generate skill uses
LABEL = "dev.blamescroll.serve"

Runner = Callable[[list[str]], tuple[int, str]]


def default_runner(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:
        return 127, str(e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


@dataclass
class Env:
    home: Path
    repo_root: Path  # the shared root: the clone, or the bundle of an installed app
    data_dir: Path
    host: str
    port: int
    runner: Runner = default_runner
    which: Callable[[str], str | None] = shutil.which
    uid: int = 0
    apply: bool = False
    force: bool = False
    installed: bool = False  # installed app (no clone): LaunchAgent runs `exe serve`
    exe: str | None = None  # the `blamescroll` executable of an installed app
    work_dir: Path | None = None  # LaunchAgent working directory in installed mode

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"


# ---- 1. MCP ----


def mcp_command(env: Env) -> list[str]:
    return [
        "claude", "mcp", "add", "--scope", "user", "--transport", "http", "blamescroll", env.url,
    ]  # fmt: skip


def install_mcp(env: Env) -> list[str]:
    cmd = mcp_command(env)
    text = " ".join(cmd)
    if not env.which("claude"):
        return ["mcp: `claude` not found on PATH. Run this yourself:", f"  {text}"]
    code, out = env.runner(["claude", "mcp", "get", "blamescroll"])
    if code == 0 and env.url in out:
        return [f"mcp: already registered at {env.url}, nothing to do"]
    if not env.apply:
        return [f"mcp: would run: {text}"]
    code, out = env.runner(cmd)
    if code != 0:
        return [f"mcp: command failed ({code}): {out.strip()}", f"  {text}"]
    return [f"mcp: registered blamescroll at {env.url}"]


# ---- 2. Skills ----


def _files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def _diff_summary(src: Path, dst: Path, rel: Path, limit: int = 12) -> list[str]:
    try:
        a = dst.read_text().splitlines(keepends=True)
        b = src.read_text().splitlines(keepends=True)
    except UnicodeDecodeError:
        return ["    (binary file differs)"]
    diff = list(difflib.unified_diff(a, b, f"installed/{rel}", f"repo/{rel}", n=0))
    out = [f"    {line.rstrip()}" for line in diff[:limit]]
    if len(diff) > limit:
        out.append(f"    ... {len(diff) - limit} more diff lines")
    return out


def install_skills(env: Env) -> list[str]:
    """Copy our skills to ~/.claude/skills and our subagent files to ~/.claude/agents."""
    src_claude = claude_dir(env.repo_root)
    items = [
        (name, src_claude / "skills" / name, env.home / ".claude" / "skills" / name, None)
        for name in SKILL_NAMES
    ] + [
        (f"agent {name}", src_claude / "agents", env.home / ".claude" / "agents", [Path(name)])
        for name in AGENT_FILES
    ]  # fmt: skip
    lines: list[str] = []
    for label, src, dst, only in items:
        todo: list[Path] = []
        blocked: list[Path] = []
        for rel in only if only is not None else _files(src):
            target = dst / rel
            if not target.exists():
                todo.append(rel)
            elif target.read_bytes() != (src / rel).read_bytes():
                (todo if env.force else blocked).append(rel)
        if blocked:
            lines.append(f"skills: skipped {label}: {dst} differs (use --force)")
            for rel in blocked:
                lines.append(f"  {rel}")
                lines += _diff_summary(src / rel, dst / rel, rel)
            continue
        if not todo:
            lines.append(f"skills: {label} unchanged")
            continue
        if not env.apply:
            lines.append(f"skills: would copy {label} to {dst}")
            continue
        for rel in todo:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / rel, dst / rel)
        lines.append(f"skills: copied {label} to {dst}")
    return lines


# ---- 3. LaunchAgent ----


def plist_path(env: Env) -> Path:
    return env.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _path_value(env: Env) -> str:
    dirs: list[str] = [str(Path(env.exe).parent)] if env.installed and env.exe else []
    for tool in ("uv", "git", "claude"):
        found = env.which(tool)
        if found:
            dirs.append(str(Path(found).parent))
    dirs += ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return ":".join(dict.fromkeys(dirs))


def build_plist(env: Env) -> dict:
    if env.installed:
        if not env.exe:
            raise FileNotFoundError("blamescroll executable not found")
        args = [env.exe, "serve"]
        work = env.work_dir or env.home
    else:
        uv = env.which("uv")
        if not uv:
            raise FileNotFoundError("uv not found on PATH")
        args = [uv, "run", "--project", str(env.repo_root), "blamescroll", "serve"]
        work = env.repo_root
    log = str(env.data_dir / "logs" / "serve.log")
    plist = {
        "Label": LABEL,
        "ProgramArguments": args,
        "WorkingDirectory": str(work),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": log,
        "StandardErrorPath": log,
        "EnvironmentVariables": {"PATH": _path_value(env)},
    }
    if env.installed:
        plist["EnvironmentVariables"]["BLAMESCROLL_HOME"] = str(work)
    return plist


def _launchctl(env: Env, verb: str) -> list[str]:
    return ["launchctl", verb, f"gui/{env.uid}", str(plist_path(env))]


def install_launchd(env: Env) -> list[str]:
    try:
        plist = build_plist(env)
    except FileNotFoundError:
        what = "`blamescroll`" if env.installed else "`uv`"
        return [f"launchd: {what} not found on PATH, cannot build the LaunchAgent"]
    data = plistlib.dumps(plist)
    plistlib.loads(data)  # validate
    path = plist_path(env)
    boot = " ".join(_launchctl(env, "bootstrap"))
    if not env.apply:
        return [
            f"launchd: would write {path}",
            f"  runs: {' '.join(plist['ProgramArguments'])}",
            f"  logs: {plist['StandardOutPath']}",
            f"launchd: would run: {boot}",
        ]
    already = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    (env.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    lines = [f"launchd: wrote {path}"]
    if not env.which("launchctl"):
        return [*lines, f"launchd: `launchctl` not found. Run this yourself: {boot}"]
    if already:  # reload so changes take effect; ignore "not loaded"
        env.runner(_launchctl(env, "bootout"))
    code, out = env.runner(_launchctl(env, "bootstrap"))
    if code != 0:
        return [*lines, f"launchd: bootstrap failed ({code}): {out.strip()}", f"  {boot}"]
    return [*lines, "launchd: loaded; `blamescroll serve` now starts at login and restarts"]


def uninstall_launchd(env: Env) -> list[str]:
    path = plist_path(env)
    out_cmd = " ".join(_launchctl(env, "bootout"))
    if not path.exists():
        return [f"launchd: {path} does not exist, nothing to remove"]
    if not env.apply:
        return [f"launchd: would run: {out_cmd}", f"launchd: would remove {path}"]
    lines = []
    if env.which("launchctl"):
        code, out = env.runner(_launchctl(env, "bootout"))
        if code != 0:
            lines.append(f"launchd: bootout said ({code}): {out.strip()}")
    else:
        lines.append(f"launchd: `launchctl` not found. Run this yourself: {out_cmd}")
    path.unlink()
    return [*lines, f"launchd: ran: {out_cmd}", f"launchd: removed {path}"]


# ---- 4. Orchestration ----

PARTS = ("mcp", "skills", "launchd")


def _undo_lines(env: Env, parts: tuple[str, ...]) -> list[str]:
    out = []
    if "mcp" in parts:
        out.append("  mcp:     claude mcp remove blamescroll --scope user")
    if "skills" in parts:
        skills = env.home / ".claude" / "skills"
        agents = env.home / ".claude" / "agents"
        paths = " ".join(
            [str(skills / n) for n in SKILL_NAMES] + [str(agents / n) for n in AGENT_FILES]
        )
        out.append(f"  skills:  rm -r {paths}")
    if "launchd" in parts:
        out.append("  launchd: blamescroll install --uninstall --launchd --apply")
    return out


def run_install(env: Env, parts: tuple[str, ...] = PARTS, uninstall: bool = False) -> list[str]:
    lines: list[str] = []
    if not env.apply:
        lines.append("DRY RUN: nothing will change. Add --apply to do it.")
    if uninstall:
        if "launchd" in parts:
            lines += uninstall_launchd(env)
        for part in parts:
            if part != "launchd":
                lines.append(f"{part}: --uninstall only handles launchd. Undo by hand:")
        lines += _undo_lines(env, tuple(p for p in parts if p != "launchd"))
        return lines
    steps = {"mcp": install_mcp, "skills": install_skills, "launchd": install_launchd}
    summary: list[str] = []
    for part in PARTS:
        if part in parts:
            part_lines = steps[part](env)
            lines += part_lines
            summary += [x for x in part_lines if x.startswith(f"{part}:")]
    lines += ["", "Checklist (what changed):" if env.apply else "Checklist (what would change):"]
    lines += [f"  - {x}" for x in summary]
    lines += ["", "To undo:", *_undo_lines(env, parts)]
    return lines
