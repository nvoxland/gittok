"""The `codescroll` command line."""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from codescroll import (
    avatars,
    db,
    learning,
    mcp_server,
    profile,
    render,
    signals,
    social,
    steering,
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
            rules=steering.list_rules(conn),
            unavailable_formats=mcp_server.unavailable_formats(cfg),
            max_illustrations=cfg.settings.render.max_illustrations_per_run,
            **mcp_server.mix_inputs(conn, cfg),
        )
    print(b.to_markdown())
    return 0


def _now() -> datetime:
    return datetime.now(UTC)


def _serve(args) -> int:
    server = load_config().settings.server
    port = args.port or server.port
    host = "0.0.0.0" if args.lan else (args.host or server.host)
    shown = "127.0.0.1" if args.lan else host
    print(f"feed: http://{shown}:{port}")
    print(f"mcp:  http://{shown}:{port}/mcp")
    if args.lan:
        for url in social.lan_urls(port):
            print(f"lan:  {url}")
        print("WARNING: the feed has no authentication. Anyone on this network can open it.")
        print("Installing the app as a PWA on a phone needs HTTPS.")
        print("It works in the browser over HTTP. Tailscale is the planned HTTPS path (M6).")
    app = create_app(
        load_config,
        render_worker=True,
        learning_worker=True,
        profile_worker=True,
        notify_worker=True,
    )
    uvicorn.run(app, host=host, port=port)
    return 0


def _notify(args) -> int:
    cfg = load_config()
    with closing(db.open_db(_db_path(cfg))) as conn:
        made = social.generate_notifications(conn, cfg, _now())
    print(" ".join(f"{k}={v}" for k, v in made.items()))
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
    p.set_defaults(fn=_serve)
    p = sub.add_parser("notify", help="generate notifications once")
    p.set_defaults(fn=_notify)
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
    p = sub.add_parser("mcp", help="stdio MCP server (fallback; prefer `serve`)")
    p.set_defaults(fn=_mcp)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, SteeringError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
