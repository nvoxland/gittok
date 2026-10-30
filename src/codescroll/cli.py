"""The `codescroll` command line."""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import closing
from pathlib import Path

import uvicorn

from codescroll import avatars, db, learning, mcp_server, render, signals, validator
from codescroll import brief as brief_mod
from codescroll.api import create_app
from codescroll.config import ConfigError, load_config


def _validate(args) -> int:
    cfg = load_config()
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cards = data["cards"] if isinstance(data, dict) else data
    accepted, rejected = validator.validate_cards(cards, cfg.repos, list(cfg.personas))
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
    for r in load_config().repos.values():
        print(f"{r.name}\t{r.ref}\t{r.group or '-'}\t{r.path}")
    return 0


def _analyze(args) -> int:
    cfg = load_config()
    names = [cfg.repo(args.repo).name] if args.repo else sorted(cfg.repos)
    with closing(db.open_db(_db_path(cfg))) as conn:
        for name in names:
            started = time.monotonic()
            res = signals.analyze(conn, cfg.repos[name], cfg.settings.analysis, force=args.force)
            secs = time.monotonic() - started
            cached = "yes" if res["cached"] else "no"
            print(f"{name} head={res['head_sha']} cached={cached} {secs:.2f}s")
    return 0


def _brief(args) -> int:
    cfg = load_config()
    names = [cfg.repo(args.repo).name] if args.repo else sorted(cfg.repos)
    with closing(db.open_db(_db_path(cfg))) as conn:
        repo_signals = {
            n: signals.analyze(conn, cfg.repos[n], cfg.settings.analysis) for n in names
        }
        b = brief_mod.build_brief(
            repo_signals=repo_signals,
            defaults=cfg.defaults,
            personas=list(cfg.personas),
            count=args.count or cfg.settings.agent.default_count,
            packet_size=cfg.settings.agent.packet_size,
            recent=mcp_server.recent_cards(conn),
        )
    print(b.to_markdown())
    return 0


def _serve(args) -> int:
    server = load_config().settings.server
    host, port = args.host or server.host, args.port or server.port
    print(f"feed: http://{host}:{port}")
    print(f"mcp:  http://{host}:{port}/mcp")
    app = create_app(load_config, render_worker=True, learning_worker=True)
    uvicorn.run(app, host=host, port=port)
    return 0


def _learn(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        res = learning.process_events(conn, cfg)
    print("impressions={impressions} rewards={rewards} weights={weights}".format(**res))
    return 0


def _reset_weights(args) -> int:
    with closing(db.open_db(_db_path(load_config()))) as conn:
        n = learning.reset_weights(conn, args.feature)
    print(f"deleted {n} weights")
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
            render.IllustrationRenderer(model=cfg.settings.render.mflux_model),
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


def _mcp(args) -> int:
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
    p = sub.add_parser("repos", help="list configured repos")
    p.set_defaults(fn=_repos)
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
    p.set_defaults(fn=_serve)
    p = sub.add_parser("learn", help="turn new impressions into rewards and update weights once")
    p.set_defaults(fn=_learn)
    p = sub.add_parser("reset-weights", help="delete learned weights (all, or one feature)")
    p.add_argument("--feature")
    p.set_defaults(fn=_reset_weights)
    p = sub.add_parser("render", help="render pending meme and illustration cards once")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=_render)
    p = sub.add_parser("avatars", help="generate persona avatar PNGs with mflux")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=_avatars)
    p = sub.add_parser("mcp", help="stdio MCP server (fallback; prefer `serve`)")
    p.set_defaults(fn=_mcp)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
