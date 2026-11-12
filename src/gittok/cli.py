"""The `gittok` command line."""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from gittok import (
    avatars,
    db,
    facts,
    gc,
    gitq,
    home,
    learning,
    mcp_server,
    profile,
    profiling,
    refit,
    render,
    signals,
    social,
    steering,
    store,
    structure,
    supply,
    validator,
)
from gittok.api import create_app
from gittok.config import ConfigError, is_clone, load_config, resolve_roots
from gittok.steering import SteeringError

FACTS_CHUNK = 5000  # the same per-call cap as the submit_facts MCP tool


def _validate(args) -> int:
    cfg = load_config()
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cards = data["cards"] if isinstance(data, dict) else data
    accepted, rejected = validator.validate_cards(
        cards,
        cfg.repos,
        list(cfg.personas),
        claim_checks=cfg.settings.agent.claim_checks,
        redact_secrets=cfg.settings.research.redact_secrets,
    )
    print(f"accepted: {len(accepted)}")
    for r in rejected:
        print(f"#{r.index} {r.reason}: {r.detail}")
    return 1 if rejected else 0


def _db_path(cfg) -> Path:
    return cfg.settings.data_dir / "gittok.db"


def _migrate(args) -> int:
    path = _db_path(load_config())
    with closing(db.open_db(path)):
        pass
    print(path)
    return 0


def _repos(args) -> int:
    if getattr(args, "repos_fn", None):
        return args.repos_fn(args)
    repos = load_config().repos
    if not repos:
        print(steering.NO_REPOS)
    for r in repos.values():
        line = f"{r.name}\t{r.ref}\t{r.group or '-'}\t{r.path}"
        print(f"{line}\t{r.remote}" if r.remote else line)
    return 0


def _need_repos(cfg) -> None:
    if not cfg.repos:
        raise SteeringError(steering.NO_REPOS)


def _analyze(args) -> int:
    cfg = load_config()
    _need_repos(cfg)
    names = [cfg.repo(args.repo).name] if args.repo else sorted(cfg.repos)
    with closing(db.open_db(_db_path(cfg))) as conn:
        for name in names:
            started = time.monotonic()
            res = signals.analyze(
                conn,
                cfg.repos[name],
                cfg.settings.analysis,
                force=args.force,
                profile=cfg.profile(name),
            )
            secs = time.monotonic() - started
            cached = "yes" if res["cached"] else "no"
            print(f"{name} head={res['head_sha']} cached={cached} {secs:.2f}s")
    return 0


def _brief(args) -> int:
    cfg = load_config()
    _need_repos(cfg)
    names = [cfg.repo(args.repo).name] if args.repo else sorted(cfg.repos)
    with closing(db.open_db(_db_path(cfg))) as conn:
        repo_signals = {
            n: signals.analyze(conn, cfg.repos[n], cfg.settings.analysis, profile=cfg.profile(n))
            for n in names
        }
        count = args.count or cfg.settings.agent.default_count
        b = mcp_server.build_brief(conn, cfg, repo_signals, count)
    print(b.to_markdown())
    return 0


def _now() -> datetime:
    return datetime.now(UTC)


_ALL_INTERFACES = social.ALL_INTERFACES
_is_loopback_host = social.is_loopback_host


def _banner(port: int, host: str, out) -> str | None:
    """Print the feed URLs to `out`. A bind that other machines can reach is token-protected:
    this also prints the pairing URLs and returns the LAN token."""
    everywhere = host in _ALL_INTERFACES
    shown = "127.0.0.1" if everywhere else host
    print(f"feed: http://{shown}:{port}", file=out)
    if _is_loopback_host(host):
        return None
    addresses = social.lan_addresses() if everywhere else [host]
    if everywhere:
        for url in social.lan_urls(port, addresses):
            print(f"lan:  {url}", file=out)
    lan_token = social.ensure_lan_token(load_config().settings.data_dir)
    for link in social.pair_links(port, lan_token, addresses):
        print(f"pair: {link['url']}", file=out)
    print("The feed is token-protected: open a pairing URL once on each device.", file=out)
    print(f"QR codes: http://127.0.0.1:{port}{social.PAIRING_PAGE} (this computer only).", file=out)
    print(
        "The feed is served to your local network over plain HTTP. Use it on a network you "
        "trust. To serve this computer only: --no-lan, or `server.lan: false`.",
        file=out,
    )
    print("PWA install and offline mode need HTTPS: service workers do not register", file=out)
    print("on plain-HTTP LAN origins. The feed still works in the browser over HTTP.", file=out)
    print('For HTTPS, see docs/install.md, "HTTPS on a LAN".', file=out)
    return lan_token


def _feed_app(lan_token: str | None):
    return create_app(
        load_config,
        render_worker=True,
        learning_worker=True,
        profile_worker=True,
        notify_worker=True,
        gc_worker=True,
        lan_token=lan_token,
    )


def _bind(args) -> tuple[str, int, bool]:
    """(host, port, lan). LAN serving binds all interfaces. It is on with `--lan`, and with
    `settings.server.lan` (the default) unless `--no-lan` or an explicit `--host` is given."""
    server = load_config().settings.server
    lan = not args.no_lan and bool(args.lan or (server.lan and not args.host))
    host = "0.0.0.0" if lan else (args.host or server.host)
    if args.no_lan and not args.host and host in _ALL_INTERFACES:
        host = "127.0.0.1"
    return host, args.port or server.port, lan


def _serve(args) -> int:
    host, port, _lan = _bind(args)
    lan_token = _banner(port, host, sys.stdout)  # None only for a loopback bind
    if not args.reload:
        parent = os.environ.get("GITTOK_PARENT_PID")
        if parent:  # started by `mcp --ui`: the session owns this server
            _watch_parent(int(parent), _stop_server)
        uvicorn.run(_feed_app(lan_token), host=host, port=port)
        return 0
    # The reloaded worker is a fresh process: it gets the token through the environment.
    if lan_token:
        os.environ["GITTOK_LAN_TOKEN"] = lan_token
    else:
        os.environ.pop("GITTOK_LAN_TOKEN", None)
    uvicorn.run(
        "gittok.cli:reload_app",
        factory=True,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
        host=host,
        port=port,
    )
    return 0


def reload_app():
    """App factory for `serve --reload`; stops the server when the MCP parent is gone."""
    parent = os.environ.get("GITTOK_PARENT_PID")
    if parent:
        _watch_parent(int(parent), _stop_reloader)
    return _feed_app(os.environ.get("GITTOK_LAN_TOKEN"))


def _stop_server() -> None:
    os.kill(os.getpid(), signal.SIGTERM)  # uvicorn shuts down cleanly on SIGTERM


def _stop_reloader() -> None:
    os.kill(os.getppid(), signal.SIGTERM)  # the uvicorn reloader, which started this worker
    os._exit(0)


def _watch_parent(pid: int, on_gone, interval: float = 1.0) -> None:
    """Call `on_gone` from a daemon thread once process `pid` no longer exists."""

    def loop():
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                on_gone()
                return
            except PermissionError:
                pass  # exists, owned by someone else
            time.sleep(interval)

    threading.Thread(target=loop, name="gittok-parent-watch", daemon=True).start()


def _notify(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        now = _now()
        made = social.generate_notifications(conn, cfg, now)
        social.generate_digests(conn, cfg, now)
    print(" ".join(f"{k}={v}" for k, v in made.items()))
    return 0


def _gc(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        counts = gc.collect(conn, cfg, _now(), dry_run=args.dry_run, vacuum=args.vacuum)
    print(json.dumps(counts, indent=2))
    return 0


def _health(args) -> int:
    cfg = load_config()
    # Keys the code ignored (a typo, or a key from another version) stay visible here.
    for w in cfg.warnings:
        print(f"GitTok config warning: {w}", file=sys.stdout if args.hint else sys.stderr)
    if args.hint:
        for line in (home.version_hint(cfg.root, home.installed_version()), _port_hint(cfg)):
            if line:
                print(line)
    if args.hint and not cfg.repos:
        # Nothing can be generated or profiled yet: one line, and no other hint.
        print(f"GitTok: {steering.NO_REPOS_AGENT}")
        return 0
    with closing(db.open_db(_db_path(cfg))) as conn:
        h = supply.feed_health(conn, cfg, _now())
        stale = [] if not args.hint else _stale_analyzer_repos(conn, cfg)
    if not args.hint:
        print(json.dumps(h, indent=2))
    else:
        # Lines for the SessionStart hook; silent when nothing is needed.
        if h["want"] > 0:
            print(
                f"GitTok feed is low: {h['backlog']} unseen cards ({h['runway_days']} days). "
                f"It wants {h['want']} more: run /gittok-generate."
            )
        line = profiling.profile_hint(cfg)
        if line:
            print(line)
        line = profiling.structure_hint(cfg)
        if line:
            print(line)
        line = facts.analyzer_hint(stale)
        if line:
            print(line)
    return 0


def feed_watch_hint(clone: bool) -> str:
    """The line that arms the feed watch. It names the command of this mode, the same one
    that the permission entry of the session settings allows."""
    return (
        f"GitTok feed watch: start `{home.feed_watch_command(clone)}` with Bash "
        "run_in_background now (once per session). When it exits, run /gittok-generate, "
        "then start the watch again."
    )


def _feed_watch(args) -> int:
    """Block until the server appends a signal line to the wants file; report it and exit.

    Only whole lines that `supply.parse_wants` accepts count. The output is built from the
    parsed time and count, never copied from the file."""
    if args.hint:
        print(feed_watch_hint(is_clone(resolve_roots()[1])))
        return 0
    cfg = load_config()
    path = cfg.settings.data_dir / supply.WANTS_FILE
    old = _read_from(path, 0)
    start = old.rfind(b"\n") + 1  # a half-written last line is read again when it is whole
    before = supply.parse_wants(old[:start].decode(errors="replace"))
    if before and _unanswered_signal(cfg, before[-1]["at"]):
        return _report_signal(before[-1])  # written while no watch ran; no run has answered it
    while True:
        size = path.stat().st_size if path.exists() else 0
        if size < start:  # the file was replaced: read it from the top
            start = 0
        if size > start:
            new = _read_from(path, start)
            whole = new.rfind(b"\n") + 1
            start += whole
            signals = supply.parse_wants(new[:whole].decode(errors="replace"))
            if signals:
                return _report_signal(signals[-1])
        time.sleep(args.poll)


def _read_from(path: Path, start: int) -> bytes:
    try:
        with path.open("rb") as f:
            f.seek(start)
            return f.read()
    except OSError:
        return b""


def _report_signal(signal: dict) -> int:
    print(
        f"{signal['at'].isoformat()} want {signal['want']} cards\n"
        "The feed wants cards: run /gittok-generate, then restart the watch."
    )
    return 0


def _unanswered_signal(cfg, signal_at: datetime) -> bool:
    """True when the signal is newer than the newest run start."""
    with closing(db.open_db(_db_path(cfg))) as conn:
        row = conn.execute("SELECT MAX(started_at) FROM runs").fetchone()
    if not row[0]:
        return True
    started = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return signal_at > started


def _stale_analyzer_repos(conn, cfg) -> list[str]:
    heads = {}
    for name, repo in cfg.repos.items():
        try:
            heads[name] = gitq.rev_parse(repo.path, repo.ref)
        except gitq.GitError:
            continue
    return facts.stale_analyzer_repos(conn, heads)


def _structure(args) -> int:
    cfg = load_config()
    needed = profiling.needed_grammars(cfg)
    missing = structure.missing(needed) if structure.available() else needed
    status = {
        "installed": structure.available(),
        "needed": needed,
        "missing": missing,
        "languages": sorted(structure.spec()["languages"]),
    }
    if not args.prefetch:
        print(json.dumps(status, indent=2))
        return 0
    if not structure.available():
        print(f"{structure.INSTALL_HINT}. Then run this command again.")
        return 1
    if not missing:
        print("All grammars are in the local cache: " + ", ".join(needed or ["(none needed)"]))
        return 0
    try:
        structure.download(missing)
    except Exception as e:  # network errors, a bad grammar name
        print(f"Download failed: {e}")
        return 1
    print("Downloaded grammars: " + ", ".join(missing))
    return 0


def _learn(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        res = learning.process_events(conn, cfg)
    print("impressions={impressions} rewards={rewards} weights={weights}".format(**res))
    return 0


def _reset_weights(args) -> int:
    with closing(db.open_db(_db_path(load_config()))) as conn:
        n = steering.reset_defaults(conn, args.feature)["deleted"]
    print(f"deleted {n} weights")
    return 0


def _table(rows: list[dict], columns: list[str]) -> str:
    """Aligned text table; None shows as '-'."""
    cells = [[("-" if r.get(c) is None else str(r.get(c))) for c in columns] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(columns)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True)).rstrip()]
    lines += [
        "  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in cells
    ]
    return "\n".join(lines)


def _show(args, data, columns: list[str] | None = None, empty: str = "nothing to show") -> None:
    """Print `data` as JSON with --json, else as a table of `columns` (or a message if empty)."""
    if args.json:
        print(json.dumps(data, indent=2))
    elif not data:
        print(empty)
    else:
        print(_table(data, columns or list(data[0])))


def _with_conn(fn):
    """Run a steering command with an open db; print SteeringError like ConfigError."""

    def run(args) -> int:
        cfg = load_config()
        with closing(db.open_db(_db_path(cfg))) as conn:
            return fn(args, cfg, conn) or 0

    return run


def _rule_text(r: dict) -> dict:
    detail = {"boost": f"x{r['factor']:g}" if r["factor"] else "", "focus": f"slots={r['slots']}"}
    detail["prefer"] = detail["boost"]
    detail["limit"] = f"max={r['max_share']:g}" if r["max_share"] is not None else ""
    return {
        "id": r["id"],
        "rule": f"{r['type']} {r['feature']}={r['value']}",
        "detail": detail.get(r["type"], ""),
        "expires": r["expires_at"],
        "by": r["created_by"],
        "reason": r["reason"] or "",
    }


def _rules(args, cfg, conn) -> int:
    action = args.rules_cmd or "list"
    if action == "add":
        rule = steering.add_rule(
            conn, cfg, type=args.type, feature=args.feature, value=args.value,
            factor=args.factor, slots=args.slots, max_share=args.max_share,
            expires=args.expires, created_by=args.created_by, reason=args.reason,
        )  # fmt: skip
        if args.json:
            print(json.dumps(rule, indent=2))
        else:
            print(f"added rule {rule['id']}: {_rule_text(rule)['rule']}")
    elif action == "remove":
        out = steering.remove_rule(conn, args.id)
        print(json.dumps(out, indent=2) if args.json else f"removed rule {args.id}")
    else:
        rules = steering.list_rules(conn, include_expired=args.all)
        data = rules if args.json else [_rule_text(r) for r in rules]
        _show(args, data, empty="no rules")
    return 0


def _weights(args, cfg, conn) -> int:
    rows = steering.explain_weights(conn, cfg, feature=args.feature)
    cols = ["feature", "value", "mean", "n", "impressions", "hit_rate", "trend"]
    _show(args, rows, cols, empty="no weights yet")
    return 0


def _profile(args, cfg, conn) -> int:
    if args.write:
        path = profile.write_profile(conn, cfg)
        print(json.dumps({"path": str(path)}) if args.json else f"wrote {path}")
        return 0
    p = steering.get_profile(conn, cfg)
    print(json.dumps(p, indent=2) if args.json else "\n".join(p["summary"]))
    return 0


def _coverage(args, cfg, conn) -> int:
    rows = steering.coverage(conn, cfg, repo=args.repo)
    _show(args, rows, ["repo", "dir", "impressions", "cards", "last_seen"], empty="no repos")
    return 0


def _cards(args, cfg, conn) -> int:
    rows = steering.recent_cards(conn, limit=args.limit)
    cols = [
        "id",
        "created_at",
        "story_type",
        "format",
        "status",
        "impressions",
        "mean_reward",
        "hook",
    ]
    _show(args, rows, cols, empty="no cards yet")
    return 0


def _card(args, cfg, conn) -> int:
    stats = steering.card_stats(conn, args.id)
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0
    print(f"card {stats['card_id']}")
    for kind, n in stats["events"].items():
        print(f"  {kind}: {n}")
    d = stats["dwell_ms"]
    print(f"  dwell ms: total {d['total']}, mean {d['mean']}")
    print(f"  rewards: {stats['rewards']} (mean {stats['mean_reward']})")
    print(f"  answers: {stats['answers']}")
    return 0


REPOS_ADD_USAGE = "gittok repos add <name> <path-or-url>"


def _repos_add(args) -> int:
    name, path = args.name, args.path
    if path is None:  # one argument: a URL, and the name comes from its last part
        remote = steering.parse_remote(name)
        if remote is None:
            raise SteeringError(f"Give a name and a path: {REPOS_ADD_USAGE}")
        path, name = remote
    remote = steering.parse_remote(path)
    if remote:
        print(f"cloning {path} (a large repo takes some minutes)", flush=True)
    # The user typed this path at a terminal, so `repos.allowed_roots` does not apply.
    out = steering.add_repo(
        load_config(),
        name,
        path,
        ref=args.ref,
        group=args.group,
        mascot=args.mascot,
        created_by="user",
        any_root=True,
    )
    if remote:
        print(f"cloned {out['remote']} into {out['path']}")
    print(f"added repo {out['name']} ({out['path']})")
    print(
        f"Next: in Claude Code, ask Claude to profile {out['name']} "
        f"(or run /gittok-profile-repo {out['name']})."
    )
    return 0


def _repos_remove(args) -> int:
    out = steering.remove_repo(load_config(), args.name)
    what = "its clone is deleted" if out["deleted_clone"] else "the directory is not touched"
    print(f"removed repo {out['name']} ({out['path']}): {what}")
    return 0


def _repos_group(args) -> int:
    if args.clear == (args.group is not None):
        raise SteeringError("Give a group name, or --clear to remove the repo from its groups.")
    out = steering.set_group(load_config(), args.repo, None if args.clear else args.group)
    print(f"{out['repo']} group: {out['group'] or '-'}")
    return 0


def _mascot_set(args) -> int:
    out = steering.set_mascot(
        load_config(), args.name, repo=args.repo, style=args.style, seed=args.seed
    )
    print(f"mascot {out['name']} repo={out['repo'] or '-'} seed={out['seed']}")
    return 0


def _persona_edit(args) -> int:
    out = steering.edit_persona(load_config(), args.handle, name=args.name, voice=args.voice)
    print(f"persona {out['handle']}: {out['name']} - {out['voice']}")
    return 0


def _render(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        if args.retry_failed:
            print(f"reset {render.retry_failed(conn)} failed cards")
        counts = render.render_pending(conn, cfg, render.default_renderers(cfg), limit=args.limit)
    print("rendered={rendered} failed={failed} waiting={waiting}".format(**counts))
    return 0


def _avatars(args) -> int:
    cfg = load_config()
    try:
        res = avatars.generate_avatars(
            cfg,
            render.IllustrationRenderer(
                model=cfg.settings.render.mflux_model, path=cfg.settings.render.mflux_path
            ),
            force=args.force,
        )
    except render.RenderError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"generated={res['generated']} skipped={res['skipped']}")
    if res["waiting"]:
        print(
            "error: mflux is not installed. In a clone, run `uv sync --group images`. "
            "For an installed tool, install the wheel again with the `images` extra "
            "(docs/install.md). Then retry.",
            file=sys.stderr,
        )
        return 1
    return 0


def _init(args) -> int:
    print("\n".join(home.init(Path(args.dir), home.installed_version())))
    return 0


def _update(args) -> int:
    target = Path(args.dir) if args.dir else resolve_roots()[1]
    if not args.dir and is_clone(target):
        raise home.InitError(
            f"{target} is a GitTok source clone, not a GitTok directory: there is nothing "
            "to update."
        )
    print("\n".join(home.update(target, home.installed_version())))
    return 0


def _server_dir(port: int) -> str | None:
    """The GitTok directory of the feed server on this computer's `port`, if one answers."""
    import httpx

    try:
        data = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2.0).json()
    except (httpx.HTTPError, ValueError):
        return None
    found = data.get("dir") if isinstance(data, dict) else None
    return found if isinstance(found, str) else None


OTHER_PORT = (
    "To serve both, the user sets another `server.port` in local/settings.yaml of one "
    "directory, then starts its session again."
)


def _port_note(cfg, port: int, owner: str | None) -> str:
    """What a session is told when its feed server did not start because the port is taken."""
    if owner is None:
        return (
            f"The feed server of this session did not start: port {port} is in use by a "
            "program that is not a GitTok feed server. The MCP tools work, but there is no "
            f"feed. Tell the user. {OTHER_PORT}"
        )
    if Path(owner) == cfg.root:
        return (
            f"The feed server of this session did not start: another Claude Code session in "
            f"this directory ({owner}) already serves the feed on port {port}. The MCP tools "
            "and the feed work. The feed stops when that session ends; then run /mcp, pick "
            "gittok, and Reconnect here to start it again."
        )
    return (
        f"The feed server of this session did not start: port {port} is in use by the feed "
        f"server of another GitTok directory, {owner}. The MCP tools here work on this "
        f"directory ({cfg.root}), but the feed on port {port} shows the cards of {owner}, "
        f"not the cards of this directory. Tell the user. {OTHER_PORT}"
    )


def _port_hint(cfg) -> str | None:
    """One SessionStart line when another GitTok directory serves this directory's port."""
    port = cfg.settings.server.port
    owner = _server_dir(port)
    if owner is None or Path(owner) == cfg.root:
        return None
    return (
        f"GitTok: port {port} is in use by the feed server of another GitTok directory, "
        f"{owner}. This session will have no feed of its own. Tell the user. {OTHER_PORT}"
    )


def _port_free(host: str, port: int) -> bool:
    """True when nothing accepts connections on `port` (checked on loopback for 0.0.0.0)."""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, port)) != 0


def _spawn_ui(cmd: list[str], env: dict) -> subprocess.Popen:
    # stdout carries the MCP protocol, so the child writes everything to stderr.
    err = sys.stderr.fileno()
    return subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=err, stderr=err)


def _stop_at_exit(proc: subprocess.Popen) -> None:
    atexit.register(proc.terminate)  # a hard kill is covered by the child's parent watch


def _refit(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        if args.export:
            ids = refit.export(conn, Path(args.export))
            print(f"exported {len(ids)} card(s) that do not fit to {args.export}")
            return 0
        res = refit.apply(conn, cfg, Path(args.apply))
    print(f"replaced {len(res['replaced'])}")
    for r in res["rejected"]:
        print(f"{r['card_id']} {r['reason']}: {r['detail']}")
    return 1 if res["rejected"] else 0


def _refeature(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        print(f"refeatured {store.refeature(conn)} card(s)")
    return 0


def _mcp(args) -> int:
    cfg = load_config()  # fails here, with one line, outside a GitTok directory
    note = None
    if args.ui:
        host, port, lan = _bind(args)
        if _port_free(host, port):
            # The child lives as long as this session. In a source clone it also reloads
            # when the feed or API code changes; an installed tool has no source to watch.
            cmd = [sys.executable, "-m", "gittok", "serve"]
            cmd += ["--reload"] if is_clone(cfg.root) else []
            cmd += ["--host", host, "--port", str(port)] + (["--lan"] if lan else [])
            env = {**os.environ, "GITTOK_PARENT_PID": str(os.getpid())}
            _stop_at_exit(_spawn_ui(cmd, env))
        else:
            note = _port_note(cfg, port, _server_dir(port))
            print(f"port {port} is in use: feed not started, MCP only. {note}", file=sys.stderr)
    mcp_server.main(note=note)
    return 0


def _submit_facts(args) -> int:
    """Store analyzer facts from JSON files (each a list of facts). Same checks as submit_facts."""
    cfg = load_config()
    r = cfg.repo(args.repo)
    items: list = []
    for f in args.files:
        data = json.loads(Path(f).read_text())
        if not isinstance(data, list):
            print(f"{f}: expected a JSON list of facts", file=sys.stderr)
            return 1
        items.extend(data)
    current = gitq.rev_parse(r.path, r.ref)
    accepted: Counter = Counter()
    rejected: list = []
    rejected_count = 0
    with closing(db.open_db(_db_path(cfg))) as conn:
        signals.analyze(conn, r, cfg.settings.analysis, profile=cfg.profile(r.name))  # cached
        for start in range(0, max(len(items), 1), FACTS_CHUNK):
            try:
                res = facts.submit_analyzer(
                    conn,
                    r.name,
                    r.path,
                    current,
                    args.head,
                    args.tool,
                    items[start : start + FACTS_CHUNK],
                )
            except facts.FactsError as e:
                print(str(e), file=sys.stderr)
                return 1
            accepted.update(res["accepted"])
            rejected_count += res["rejected_count"]
            rejected.extend({**x, "index": x["index"] + start} for x in res["rejected"])
    counts = " ".join(f"{k}={n}" for k, n in sorted(accepted.items()))
    print(f"{r.name} tool={args.tool} {counts} rejected={rejected_count}")
    for x in rejected[:10]:
        print(f"  #{x['index']} {x['reason']}: {json.dumps(x['fact'])[:160]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gittok",
        description="GitTok runs in a GitTok directory. Make one with `gittok init <dir>`, "
        "then start Claude Code there. The other commands work only inside such a directory.",
    )
    parser.add_argument("--version", action="version", version=f"gittok {home.installed_version()}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "init",
        help="make a GitTok directory (the path must be new or empty)",
        description="Make a GitTok directory: the MCP entry, the skills and agents, the "
        "session hooks, and a place for your cards and settings. The directory is made if "
        "it does not exist. A directory that is not empty is refused. Nothing is written "
        "outside it.",
    )
    p.add_argument("dir", help="the directory to make, for example ~/gittok")
    p.set_defaults(fn=_init)
    p = sub.add_parser(
        "update",
        help="rewrite the files that `init` made, after an upgrade of the tool",
        description="Rewrite .mcp.json, the skills, the agents, the session settings and "
        "CLAUDE.md of a GitTok directory with the files of the installed version. A file "
        "that you edited is saved as <name>.bak first. local/, data/ and repos/ are not "
        "touched.",
    )
    p.add_argument("dir", nargs="?", help="the GitTok directory (default: the one you are in)")
    p.set_defaults(fn=_update)
    p = sub.add_parser("validate", help="validate a JSON file of cards (does not store)")
    p.add_argument("file")
    p.set_defaults(fn=_validate)
    p = sub.add_parser("migrate", help="create or migrate the database")
    p.set_defaults(fn=_migrate)
    p = sub.add_parser("repos", help="list configured repos (or: add, remove, group)")
    p.set_defaults(fn=_repos, repos_fn=None)
    rsub = p.add_subparsers(dest="repos_cmd")
    q = rsub.add_parser(
        "add",
        help="add a git repo: a local directory, or a remote URL that GitTok clones",
        description="Add a repo to local/repos.yaml. Give a local git checkout, or a remote "
        "(https://, ssh://, git:// or user@host:path). GitTok clones a remote into the GitTok "
        "directory (repos/<name>) and fetches it before each analysis.",
    )
    q.add_argument("name", help="repo name (optional for a URL: default is its last part)")
    q.add_argument("path", nargs="?", metavar="path-or-url")
    q.add_argument("--ref", help="branch to read (default: HEAD, or the remote default branch)")
    q.add_argument("--group")
    q.add_argument("--mascot")
    q.set_defaults(repos_fn=_repos_add)
    q = rsub.add_parser(
        "remove", help="remove a repo; a clone that GitTok made is deleted, your own is not"
    )
    q.add_argument("name")
    q.set_defaults(repos_fn=_repos_remove)
    q = rsub.add_parser("group", help="put a repo in a group")
    q.add_argument("repo")
    q.add_argument("group", nargs="?")
    q.add_argument("--clear", action="store_true", help="remove the repo from its groups")
    q.set_defaults(repos_fn=_repos_group)
    p = sub.add_parser("analyze", help="compute git signals (cached by HEAD)")
    p.add_argument("--repo")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_analyze)
    p = sub.add_parser(
        "submit-facts", help="store analyzer facts from JSON files (same checks as submit_facts)"
    )
    p.add_argument("--repo", required=True)
    p.add_argument("--head", required=True, help="the head sha the analyzer ran on")
    p.add_argument("--tool", required=True, help="tool label, such as 'clj-kondo 2026.05.25'")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=_submit_facts)
    p = sub.add_parser("brief", help="print the brief without opening a run")
    p.add_argument("--repo")
    p.add_argument("--count", type=int)
    p.set_defaults(fn=_brief)
    p = sub.add_parser("serve", help="serve the feed and the web app by hand, with no session")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument(
        "--lan",
        action="store_true",
        help="serve the local network: bind 0.0.0.0 and print pairing URLs (the default, "
        "from server.lan in the settings)",
    )
    p.add_argument("--no-lan", action="store_true", help="serve this computer only (127.0.0.1)")
    p.add_argument("--reload", action="store_true", help="restart when src/gittok changes")
    p.set_defaults(fn=_serve)
    p = sub.add_parser("mcp", help="the MCP server (stdio); --ui also serves the feed")
    p.add_argument("--ui", action="store_true", help="serve the feed while the session runs")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--lan", action="store_true", help="with --ui: serve the local network")
    p.add_argument("--no-lan", action="store_true", help="with --ui: serve this computer only")
    p.set_defaults(fn=_mcp)
    p = sub.add_parser("refit", help="rewrite stored cards that do not fit the card front")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--export", metavar="DIR", help="write cards that do not fit as JSON files")
    g.add_argument("--apply", metavar="DIR", help="validate rewritten files and replace cards")
    p.set_defaults(fn=_refit)
    p = sub.add_parser("refeature", help="recompute stored card features from each card's spec")
    p.set_defaults(fn=_refeature)
    p = sub.add_parser("notify", help="generate notifications once")
    p.set_defaults(fn=_notify)
    p = sub.add_parser(
        "health", help="print feed health (backlog, runway, how many to make) as JSON"
    )
    p.add_argument("--hint", action="store_true", help="one reminder line if cards are wanted")
    p.set_defaults(fn=_health)
    p = sub.add_parser(
        "feed-watch", help="wait until the server says the feed wants cards, then exit"
    )
    p.add_argument("--hint", action="store_true", help="print the line that arms the watch")
    p.add_argument("--poll", type=float, default=10.0, help="seconds between file checks")
    p.set_defaults(fn=_feed_watch)
    p = sub.add_parser(
        "structure", help="tree-sitter structure layer: status, and --prefetch for its grammars"
    )
    p.add_argument(
        "--prefetch",
        action="store_true",
        help="download the grammars for the languages in the configured repos (needs network)",
    )
    p.set_defaults(fn=_structure)
    p = sub.add_parser("gc", help="delete old cards, events, and files (prints counts as JSON)")
    p.add_argument("--dry-run", action="store_true", help="count what would go; change nothing")
    p.add_argument("--vacuum", action="store_true", help="shrink the database file afterwards")
    p.set_defaults(fn=_gc)
    p = sub.add_parser("learn", help="turn new impressions into rewards and update weights once")
    p.set_defaults(fn=_learn)
    p = sub.add_parser("reset-weights", help="delete learned weights (all, or one feature)")
    p.add_argument("--feature")
    p.set_defaults(fn=_reset_weights)

    def steer(name, fn, help_, json_flag=True):
        q = sub.add_parser(name, help=help_)
        if json_flag:
            q.add_argument("--json", action="store_true", help="print JSON")
        q.set_defaults(fn=_with_conn(fn))
        return q

    p = steer("rules", _rules, "list, add, or remove steering rules (default: list)")
    p.set_defaults(rules_cmd=None, all=False)
    p.add_argument("--all", action="store_true", help="include expired rules")
    rsub = p.add_subparsers(dest="rules_cmd")
    q = rsub.add_parser("list", help="list active rules")
    q.add_argument("--all", action="store_true", help="include expired rules")
    q.add_argument("--json", action="store_true")
    q = rsub.add_parser("add", help="add a rule")
    q.add_argument("--type", required=True, choices=steering.RULE_TYPES)
    q.add_argument("--feature", required=True)
    q.add_argument("--value", required=True)
    q.add_argument("--factor", type=float)
    q.add_argument("--slots", type=int)
    q.add_argument("--max-share", type=float, dest="max_share")
    q.add_argument("--expires", help="date, or 7d / 2w / 12h")
    q.add_argument("--reason", default="")
    q.add_argument("--created-by", default="user", dest="created_by")
    q.add_argument("--json", action="store_true")
    q = rsub.add_parser("remove", help="remove a rule by id")
    q.add_argument("id", type=int)
    q.add_argument("--json", action="store_true")
    p = steer("weights", _weights, "explain learned weights per feature value")
    p.add_argument("--feature")
    p = steer("profile", _profile, "print the taste profile (or --write profile.md)")
    p.add_argument("--write", action="store_true")
    p = steer("coverage", _coverage, "how much of each repo's top-level dirs you have seen")
    p.add_argument("--repo")
    p = steer("cards", _cards, "recent cards and how they did")
    p.add_argument("--limit", type=int, default=20)
    p = steer("card", _card, "event, dwell, reward, and answer stats for one card")
    p.add_argument("id")
    p = sub.add_parser("mascot", help="manage mascots")
    msub = p.add_subparsers(dest="mascot_cmd", required=True)
    q = msub.add_parser("set", help="create or change a mascot")
    q.add_argument("name")
    q.add_argument("--repo")
    q.add_argument("--style")
    q.add_argument("--seed", type=int)
    q.set_defaults(fn=_mascot_set)
    p = sub.add_parser("persona", help="manage personas")
    psub = p.add_subparsers(dest="persona_cmd", required=True)
    q = psub.add_parser("edit", help="change a persona's name or voice")
    q.add_argument("handle")
    q.add_argument("--name")
    q.add_argument("--voice")
    q.set_defaults(fn=_persona_edit)
    p = sub.add_parser("render", help="render pending meme and illustration cards once")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=_render)
    p = sub.add_parser("avatars", help="generate persona avatar PNGs with mflux")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_avatars)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, SteeringError, home.InitError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
