"""The `codescroll` command line."""

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
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from codescroll import (
    avatars,
    candidate_leads,
    db,
    gc,
    install,
    knowledge,
    learning,
    ledger,
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
from codescroll import brief as brief_mod
from codescroll.api import create_app
from codescroll.config import ConfigError, load_config
from codescroll.steering import SteeringError


def _validate(args) -> int:
    cfg = load_config()
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cards = data["cards"] if isinstance(data, dict) else data
    accepted, rejected = validator.validate_cards(
        cards, cfg.repos, list(cfg.personas), claim_checks=cfg.settings.agent.claim_checks
    )
    print(f"accepted: {len(accepted)}")
    for r in rejected:
        print(f"#{r.index} {r.reason}: {r.detail}")
    return 1 if rejected else 0


def _db_path(cfg) -> Path:
    return cfg.settings.data_dir / "codescroll.db"


def _migrate(args) -> int:
    path = _db_path(load_config())
    with closing(db.open_db(path)):
        pass
    print(path)
    return 0


def _repos(args) -> int:
    if getattr(args, "repos_fn", None):
        return args.repos_fn(args)
    for r in load_config().repos.values():
        print(f"{r.name}\t{r.ref}\t{r.group or '-'}\t{r.path}")
    return 0


def _analyze(args) -> int:
    cfg = load_config()
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
    names = [cfg.repo(args.repo).name] if args.repo else sorted(cfg.repos)
    with closing(db.open_db(_db_path(cfg))) as conn:
        repo_signals = {
            n: signals.analyze(conn, cfg.repos[n], cfg.settings.analysis, profile=cfg.profile(n))
            for n in names
        }
        b = brief_mod.build_brief(
            repo_signals=repo_signals,
            defaults=cfg.defaults,
            personas=list(cfg.personas),
            count=args.count or cfg.settings.agent.default_count,
            packet_size=cfg.settings.agent.packet_size,
            recent=mcp_server.recent_cards(conn),
            meme_templates=cfg.meme_templates,
            template_weights=mcp_server.template_weights(conn, cfg),
            rules=steering.list_rules(conn),
            unavailable_formats=mcp_server.unavailable_formats(cfg),
            max_illustrations=cfg.settings.render.max_illustrations_per_run,
            ledger=ledger.for_brief(
                conn, cfg, sorted(repo_signals), datetime.now(UTC), analyses=repo_signals
            ),
            lead_ok=ledger.offerable(conn, cfg, datetime.now(UTC)),
            variants=ledger.variants(conn, cfg, datetime.now(UTC)),
            variant_max_share=cfg.settings.agent.variant_max_share,
            intro_share=cfg.settings.agent.intro_share,
            min_spot_the_bug=cfg.settings.agent.min_spot_the_bug_per_run,
            novelty=knowledge.novelty_maps(conn, cfg, sorted(repo_signals)),
            intro_prefer={r: candidate_leads.dirs_with_core(conn, r) for r in repo_signals},
            filesets={r: cfg.fileset(r) for r in repo_signals},
            **mcp_server.mix_inputs(conn, cfg),
        )
    print(b.to_markdown())
    return 0


def _now() -> datetime:
    return datetime.now(UTC)


def _banner(port: int, host: str, lan: bool, out) -> str | None:
    """Print the feed URLs to `out`; with `lan`, also the pairing URLs. Returns the LAN token."""
    shown = "127.0.0.1" if lan else host
    print(f"feed: http://{shown}:{port}", file=out)
    print(f"mcp:  http://{shown}:{port}/mcp", file=out)
    if not lan:
        return None
    for url in social.lan_urls(port):
        print(f"lan:  {url}", file=out)
    lan_token = social.ensure_lan_token(load_config().settings.data_dir)
    for a in social.lan_addresses():
        print(f"pair: http://{a}:{port}/pair?t={lan_token}", file=out)
    print("The feed is token-protected: open a pairing URL once on each device.", file=out)
    print("MCP (/mcp) is loopback-only and is never reachable from the LAN.", file=out)
    print("PWA install and offline mode need HTTPS: service workers do not register", file=out)
    print("on plain-HTTP LAN origins. The feed still works in the browser over HTTP.", file=out)
    print("Tailscale is the planned HTTPS path (M6).", file=out)
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


def _bind(args) -> tuple[str, int]:
    server = load_config().settings.server
    host = "0.0.0.0" if args.lan else (args.host or server.host)
    return host, args.port or server.port


def _serve(args) -> int:
    host, port = _bind(args)
    lan_token = _banner(port, host, args.lan, sys.stdout)
    if not args.reload:
        uvicorn.run(_feed_app(lan_token), host=host, port=port)
        return 0
    # The reloaded worker is a fresh process: it gets the token through the environment.
    if lan_token:
        os.environ["CODESCROLL_LAN_TOKEN"] = lan_token
    else:
        os.environ.pop("CODESCROLL_LAN_TOKEN", None)
    uvicorn.run(
        "codescroll.cli:reload_app",
        factory=True,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
        host=host,
        port=port,
    )
    return 0


def reload_app():
    """App factory for `serve --reload`; stops the server when the MCP parent is gone."""
    parent = os.environ.get("CODESCROLL_PARENT_PID")
    if parent:
        _watch_parent(int(parent), _stop_reloader)
    return _feed_app(os.environ.get("CODESCROLL_LAN_TOKEN"))


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

    threading.Thread(target=loop, name="codescroll-parent-watch", daemon=True).start()


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
    with closing(db.open_db(_db_path(cfg))) as conn:
        h = supply.feed_health(conn, cfg, _now())
    if not args.hint:
        print(json.dumps(h, indent=2))
    else:
        # Lines for the SessionStart hook; silent when nothing is needed.
        if h["want"] > 0:
            print(
                f"CodeScroll feed is low: {h['backlog']} unseen cards ({h['runway_days']} days). "
                f"It wants {h['want']} more: offer to run /codescroll-generate."
            )
        line = profiling.profile_hint(cfg)
        if line:
            print(line)
        line = profiling.structure_hint(cfg)
        if line:
            print(line)
    return 0


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


def _repos_add(args) -> int:
    out = steering.add_repo(
        load_config(), args.name, args.path, ref=args.ref, group=args.group, mascot=args.mascot
    )
    print(f"added repo {out['name']} ({out['path']})")
    print(out["next"])
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
            "error: mflux is not installed. Run `uv sync --group images` and retry.",
            file=sys.stderr,
        )
        return 1
    return 0


def _install_env(cfg, args) -> install.Env:
    server = cfg.settings.server
    return install.Env(
        home=Path.home(),
        repo_root=cfg.root,
        data_dir=cfg.settings.data_dir,
        host=server.host,
        port=server.port,
        uid=os.getuid(),
        apply=args.apply,
        force=args.force,
    )


def _install(args) -> int:
    cfg = load_config()
    parts = tuple(p for p in install.PARTS if getattr(args, p)) or install.PARTS
    env = _install_env(cfg, args)
    print("\n".join(install.run_install(env, parts, uninstall=args.uninstall)))
    return 0


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
    if args.ui:
        host, port = _bind(args)
        if _port_free(host, port):
            # A child `serve --reload` picks up feed and API code changes on save.
            cmd = [sys.executable, "-m", "codescroll", "serve", "--reload"]
            cmd += ["--host", host, "--port", str(port)] + (["--lan"] if args.lan else [])
            env = {**os.environ, "CODESCROLL_PARENT_PID": str(os.getpid())}
            _stop_at_exit(_spawn_ui(cmd, env))
        else:
            print(f"port {port} is in use: feed not started, MCP only", file=sys.stderr)
    mcp_server.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codescroll")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="validate a JSON file of cards (does not store)")
    p.add_argument("file")
    p.set_defaults(fn=_validate)
    p = sub.add_parser("migrate", help="create or migrate the database")
    p.set_defaults(fn=_migrate)
    p = sub.add_parser("repos", help="list configured repos (or: add, group)")
    p.set_defaults(fn=_repos, repos_fn=None)
    rsub = p.add_subparsers(dest="repos_cmd")
    q = rsub.add_parser("add", help="add a git repo to config/repos.yaml")
    q.add_argument("name")
    q.add_argument("path")
    q.add_argument("--ref")
    q.add_argument("--group")
    q.add_argument("--mascot")
    q.set_defaults(repos_fn=_repos_add)
    q = rsub.add_parser("group", help="put a repo in a group")
    q.add_argument("repo")
    q.add_argument("group", nargs="?")
    q.add_argument("--clear", action="store_true", help="remove the repo from its groups")
    q.set_defaults(repos_fn=_repos_group)
    p = sub.add_parser("analyze", help="compute git signals (cached by HEAD)")
    p.add_argument("--repo")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_analyze)
    p = sub.add_parser("brief", help="print the brief without opening a run")
    p.add_argument("--repo")
    p.add_argument("--count", type=int)
    p.set_defaults(fn=_brief)
    p = sub.add_parser("serve", help="serve the feed, web app, and MCP endpoint")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--lan", action="store_true", help="bind 0.0.0.0 and print LAN URLs")
    p.add_argument("--reload", action="store_true", help="restart when src/codescroll changes")
    p.set_defaults(fn=_serve)
    p = sub.add_parser("mcp", help="stdio MCP server; --ui also serves the feed")
    p.add_argument("--ui", action="store_true", help="serve the feed while the session runs")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--lan", action="store_true", help="with --ui: bind 0.0.0.0, print LAN URLs")
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
    p = sub.add_parser("install", help="register MCP, copy skills, add a LaunchAgent (dry run)")
    p.add_argument("--apply", action="store_true", help="make the changes (default: print only)")
    p.add_argument("--force", action="store_true", help="overwrite differing skill files")
    p.add_argument("--uninstall", action="store_true", help="remove the LaunchAgent")
    p.add_argument("--mcp", action="store_true", help="only the MCP entry")
    p.add_argument("--skills", action="store_true", help="only the skills")
    p.add_argument("--launchd", action="store_true", help="only the LaunchAgent")
    p.set_defaults(fn=_install)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, SteeringError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
