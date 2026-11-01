"""Agent run lifecycle: open, submit cards, finish."""

from __future__ import annotations

import json
import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta

from codescroll import db, ledger, signals, store, validator


class RunError(Exception):
    """Message is shown to the agent: keep it short and actionable."""


class RunLimitError(RunError):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id(now: datetime) -> str:
    return f"r_{int(now.timestamp() * 1000):012x}{secrets.token_hex(4)}"


def open_run(
    conn,
    cfg,
    *,
    repo: str | None,
    brief: str,
    requested: int,
    packets: list[dict] | None = None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    max_count = cfg.settings.agent.max_count
    if not 1 <= requested <= max_count:
        raise RunError(f"requested must be between 1 and {max_count}; got {requested}")
    expire_stale(conn, now=now)
    limit = cfg.settings.agent.per_day_runs
    recent = [
        r[0]
        for r in conn.execute(
            "SELECT started_at FROM runs WHERE status != 'expired' AND started_at > ? "
            "ORDER BY started_at",
            (_iso(now - timedelta(hours=24)),),
        )
    ]
    if len(recent) >= limit:
        free_at = datetime.strptime(recent[-limit], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        retry = _iso(free_at + timedelta(hours=24))
        raise RunLimitError(f"daily run limit reached ({limit}); try again after {retry}")
    run_id = _new_run_id(now)
    repo_id = store.ensure_repo(conn, cfg.repos[repo]) if repo else None
    with conn:
        conn.execute(
            "INSERT INTO runs(id, repo_id, status, brief, requested, meta, started_at) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?)",
            (
                run_id,
                repo_id,
                brief,
                requested,
                db.dumps({"mcp_calls": {}, "packets": packets or []}),
                _iso(now),
            ),
        )
    return run_id


def get_run(conn, run_id) -> dict | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["reject_reasons"] = db.loads(out["reject_reasons"])
    out["meta"] = db.loads(out["meta"])
    return out


MAX_CARDS_PER_CALL = 40


def get_packet(conn, run_id: str, packet_id: str) -> dict:
    run = get_run(conn, run_id)
    if run is None:
        raise RunError(f"unknown run {run_id}; call get_brief for a new run")
    for pk in run["meta"].get("packets") or []:
        if pk["id"] == packet_id:
            return pk
    raise RunError(f"unknown packet {packet_id} in run {run_id}")


def _card_list(cards: list | dict) -> list:
    if isinstance(cards, dict):
        cards = cards.get("cards")
    if not isinstance(cards, list):
        raise RunError('submit {"cards": [...]} or a list of card objects')
    if len(cards) > MAX_CARDS_PER_CALL:
        raise RunError(f"at most {MAX_CARDS_PER_CALL} cards per call; got {len(cards)}")
    return cards


def _validate(conn, cfg, run: dict, cards: list, lead_refs: list[dict] | None = None):
    max_images = cfg.settings.render.max_illustrations_per_run
    # A variant retells a story in a format its packet named, even one the story type's list lacks.
    variants = {
        (r["story_type"], r["format"])
        for pk in run["meta"].get("packets") or []
        for r in pk.get("lead_refs") or []
        if r.get("kind") == "variant" and r.get("format") and r.get("story_type")
    }
    return validator.validate_cards(
        cards,
        cfg.repos,
        list(cfg.personas),
        meme_templates=cfg.meme_templates,
        mascots=cfg.mascots,
        signals_for=lambda name: signals.load_signals(conn, name),
        illustration_budget=max(0, max_images - run["meta"].get("illustrations", 0)),
        claim_checks=cfg.settings.agent.claim_checks,
        lead_texts=[x["text"] for x in lead_refs if x.get("text")] if lead_refs else None,
        variant_formats=variants,
    )


_NOT_THE_CARDS_FAULT = frozenset({"over_quota", "illustration_budget"})


def _cited_lead(card, lead_refs: list[dict]) -> dict | None:
    """The packet lead a (possibly malformed) submitted card cited."""
    if not isinstance(card, dict):
        return None
    try:
        return ledger.match_lead(card, lead_refs)
    except (TypeError, AttributeError):
        return None


def _duplicate_why(conn, cfg, a, seen: set[str]) -> str | None:
    """Why an accepted card is a duplicate story; None if it is new or an allowed variant."""
    if a.story_key in seen:
        return "already in this submission"
    return store.story_blocker(conn, a.story_key, a.card["format"], cfg.settings.agent)


def check(conn, cfg, run_id: str, cards: list | dict) -> dict:
    """Validate without storing: the same git checks as submit, plus duplicate stories.

    Run quota and illustration budget are not checked here; submit decides those.
    """
    cards = _card_list(cards)
    run = get_run(conn, run_id)
    _check_open(run, run_id)
    accepted, rejected = _validate(conn, cfg, run, cards)
    ok: list[int] = []
    seen: set[str] = set()
    for a in accepted:
        if why := _duplicate_why(conn, cfg, a, seen):
            rejected.append(validator.Rejection(a.index, "duplicate_story", why))
        else:
            seen.add(a.story_key)
            ok.append(a.index)
    rejected.sort(key=lambda r: r.index)
    return {"ok": ok, "rejected": [r.as_dict() for r in rejected]}


def submit(conn, cfg, run_id: str, cards: list | dict, packet_id: str | None = None) -> dict:
    raw = cards
    cards = _card_list(cards)
    lead_refs: list[dict] = []
    if packet_id is not None:
        lead_refs = get_packet(conn, run_id, packet_id).get("lead_refs") or []
    run0 = get_run(conn, run_id)
    _check_open(run0, run_id)
    max_images = cfg.settings.render.max_illustrations_per_run
    # Git validation is slow: do it before taking the write lock.
    accepted, rejected = _validate(conn, cfg, run0, cards, lead_refs)
    out_dir = cfg.settings.data_dir / "runs" / run_id
    stored: list[dict] = []
    with db.immediate(conn):
        run = get_run(conn, run_id)
        _check_open(run, run_id)
        n = run["submissions"] + 1
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"submission-{n}.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False))
        quota = run["requested"] - run["accepted"] if run["requested"] is not None else None
        seen: set[str] = set()
        used = run["meta"].get("illustrations", 0)  # re-read under the lock
        for a in accepted:
            cost = validator.illustration_cost(a.card)
            if why := _duplicate_why(conn, cfg, a, seen):
                rejected.append(validator.Rejection(a.index, "duplicate_story", why))
            elif used + cost > max_images:
                rejected.append(
                    validator.Rejection(
                        a.index, "illustration_budget", "run illustration budget is used up"
                    )
                )
            elif quota is not None and len(stored) >= quota:
                rejected.append(
                    validator.Rejection(a.index, "over_quota", "run quota is already filled")
                )
            else:
                seen.add(a.story_key)
                used += cost
                card_id = store.insert_card(conn, cfg, run_id, a)
                if used_lead := ledger.match_lead(a.card, lead_refs):
                    conn.execute(
                        "UPDATE cards SET lead_id = ? WHERE id = ?", (used_lead["id"], card_id)
                    )
                    ledger.mark_covered(conn, used_lead["id"], datetime.now(UTC))
                stored.append({"index": a.index, "card_id": card_id})
        rejected.sort(key=lambda r: r.index)
        # A card rejected for its own fault counts against the lead it cited.
        for r in rejected:
            if r.reason not in _NOT_THE_CARDS_FAULT and (
                lead := _cited_lead(cards[r.index], lead_refs)
            ):
                ledger.mark_rejected(conn, lead["id"], datetime.now(UTC))
        rej = [r.as_dict() for r in rejected]
        reasons = run["reject_reasons"] + [
            {**r, "submission": n, **({"packet": packet_id} if packet_id else {})} for r in rej
        ]
        meta = {**run["meta"], "illustrations": used}
        if packet_id is not None:
            results = dict(meta.get("packet_results") or {})
            prev = results.get(packet_id) or {"accepted": 0, "rejected": 0, "submissions": 0}
            results[packet_id] = {
                "accepted": prev["accepted"] + len(stored),
                "rejected": prev["rejected"] + len(rej),
                "submissions": prev["submissions"] + 1,
            }
            meta["packet_results"] = results
        conn.execute(
            "UPDATE runs SET accepted = accepted + ?, rejected = rejected + ?, "
            "submissions = ?, reject_reasons = ?, meta = ? WHERE id = ?",
            (
                len(stored),
                len(rej),
                n,
                db.dumps(reasons),
                db.dumps(meta),
                run_id,
            ),
        )
        run = get_run(conn, run_id)
    return {
        "run_id": run_id,
        "submission": n,
        "accepted": stored,
        "rejected": rej,
        "totals": {
            "accepted": run["accepted"],
            "rejected": run["rejected"],
            "requested": run["requested"],
            "remaining": max(0, run["requested"] - run["accepted"]),
        },
    }


def _check_open(run: dict | None, run_id: str) -> None:
    if run is None:
        raise RunError(f"unknown run {run_id}; call get_brief for a new run")
    if run["status"] != "open":
        raise RunError(f"run {run_id} is {run['status']}; call get_brief for a new run")


def _summary(run: dict) -> dict:
    counts = Counter(r["reason"] for r in run["reject_reasons"])
    return {
        "run_id": run["id"],
        "status": run["status"],
        "accepted": run["accepted"],
        "rejected": run["rejected"],
        "submissions": run["submissions"],
        "duration_ms": run["duration_ms"],
        "seconds_per_card": (
            round(run["duration_ms"] / 1000 / run["accepted"], 1)
            if run["accepted"] and run["duration_ms"] is not None
            else None
        ),
        "top_reject_reasons": [[k, v] for k, v in counts.most_common(5)],
        "mcp_calls": run["meta"].get("mcp_calls", {}),
        "packets": run["meta"].get("packet_results", {}),
    }


def finish_run(conn, run_id: str, notes: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    run = get_run(conn, run_id)
    if run is None:
        raise RunError(f"unknown run {run_id}; call get_brief for a new run")
    if run["status"] == "open":
        started = datetime.strptime(run["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        duration_ms = int((now - started).total_seconds() * 1000)
        meta = {**run["meta"], "notes": notes}
        with conn:
            conn.execute(
                "UPDATE runs SET status = 'finished', finished_at = ?, duration_ms = ?, "
                "meta = ? WHERE id = ?",
                (_iso(now), duration_ms, db.dumps(meta), run_id),
            )
        run = get_run(conn, run_id)
    return _summary(run)


def expire_stale(conn, hours: int = 24, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    with conn:
        cur = conn.execute(
            "UPDATE runs SET status = 'expired' WHERE status = 'open' AND started_at < ?",
            (_iso(now - timedelta(hours=hours)),),
        )
    return cur.rowcount


def bump_call(conn, run_id: str, tool: str) -> None:
    """Count one tool call on an open run, in a single atomic UPDATE."""
    key = f'"{tool}"'
    with conn:
        conn.execute(
            "UPDATE runs SET meta = json_set(meta, '$.mcp_calls', json_set("
            "COALESCE(json_extract(meta, '$.mcp_calls'), json('{}')), '$.' || ?, "
            "COALESCE(json_extract(meta, '$.mcp_calls.' || ?), 0) + 1)) "
            "WHERE id = ? AND status = 'open'",
            (key, key, run_id),
        )
