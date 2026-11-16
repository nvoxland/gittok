"""Rewrite stored cards that no longer fit the card front (validator._check_fit).

`export` writes one JSON file per card that fails the check; an agent shortens the files;
`apply` validates each rewrite like a submission and replaces the card in place, so its id,
events, likes, and saves stay attached.
"""

from __future__ import annotations

import json
from pathlib import Path

from gittok import db, signals, store, validator


def export(conn, out_dir: Path) -> list[str]:
    """Write `<card_id>.json` = {card_id, problem, card} for each card that does not fit."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = []
    for row in conn.execute("SELECT id, spec FROM cards ORDER BY created_at, id"):
        card = db.loads(row["spec"])
        try:
            validator._check_fit(card)
        except validator._Reject as r:
            data = {"card_id": row["id"], "problem": r.detail, "card": card}
            (out_dir / f"{row['id']}.json").write_text(json.dumps(data, indent=2))
            ids.append(row["id"])
    return ids


def apply(conn, cfg, in_dir: Path) -> dict:
    """Validate each rewrite in `in_dir` and replace the stored card when it passes."""
    replaced: list[str] = []
    rejected: list[dict] = []
    for path in sorted(in_dir.glob("*.json")):
        data = json.loads(path.read_text())
        card_id, card = data["card_id"], data["card"]
        row = conn.execute(
            "SELECT spec, status, resolved FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        if row is None:
            rejected.append({"card_id": card_id, "reason": "unknown_card", "detail": ""})
            continue
        old = db.loads(row["spec"])
        if card.get("story_type") != old["story_type"]:
            detail = f"was {old['story_type']}; a refit keeps the story"
            rejected.append({"card_id": card_id, "reason": "story_changed", "detail": detail})
            continue
        accepted, rejects = validator.validate_cards(
            [card],
            cfg.repos,
            list(cfg.personas),
            meme_templates=cfg.meme_templates,
            mascots=cfg.mascots,
            signals_for=lambda name: signals.load_signals(conn, name),
            claim_checks=cfg.settings.agent.claim_checks,
            redact_secrets=cfg.settings.research.redact_secrets,
            facts_conn=conn,
            require_facts=cfg.settings.agent.require_facts,
            require_claim_sources=cfg.settings.agent.require_claim_sources,
            # the card keeps the format it has, even a variant its story type does not list
            variant_formats={(old["story_type"], old["format"])},
        )
        if rejects:
            r = rejects[0]
            rejected.append({"card_id": card_id, "reason": r.reason, "detail": r.detail})
            continue
        a = accepted[0]
        clash = conn.execute(
            "SELECT 1 FROM cards WHERE story_key = ? AND format = ? AND id != ?",
            (a.story_key, a.card["format"], card_id),
        ).fetchone()
        if clash:
            detail = "another card has this story and format"
            rejected.append({"card_id": card_id, "reason": "duplicate_story", "detail": detail})
            continue
        _replace(conn, cfg, card_id, accepted[0], old, row["status"], db.loads(row["resolved"]))
        replaced.append(card_id)
    return {"replaced": replaced, "rejected": rejected}


def _replace(conn, cfg, card_id: str, acc, old: dict, status: str, old_resolved=None) -> None:
    card = acc.card
    drawn = card["visual"]["kind"] in store.RENDERED_KINDS
    redraw = drawn and card["visual"] != old["visual"]
    resolved = acc.resolved
    if drawn and not redraw and isinstance(old_resolved, dict):
        # The picture did not change: keep what the renderer drew. The status stays as it
        # was, so nothing would draw it again.
        resolved = {**resolved, "visual": old_resolved.get("visual")}
    if drawn and isinstance(old_resolved, dict) and "image_backend" in old_resolved:
        # The card keeps its renderer: the local worker skips only cards assigned elsewhere.
        resolved = {**resolved, "image_backend": old_resolved["image_backend"]}
    with conn:
        conn.execute(
            "UPDATE cards SET format = ?, persona = ?, tone = ?, spec = ?, resolved = ?, "
            "status = ?, story_key = ? WHERE id = ?",
            (
                card["format"],
                card["persona"],
                card["tone"],
                db.dumps(card),
                db.dumps(resolved),
                "pending_render" if redraw else status,
                acc.story_key,
                card_id,
            ),
        )
        _keep_story(conn, acc, card)
        store.set_features(conn, card_id, card, cfg)


def _keep_story(conn, acc, card: dict) -> None:
    """The story of the card (its key and formats) follows the rewritten card."""
    now = db.now_iso()
    conn.execute(
        "INSERT INTO stories(story_key, repo, story_type, sources, first_card_at, last_card_at, "
        "formats) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(story_key) DO NOTHING",
        (
            acc.story_key,
            card["repos"][0],
            card["story_type"],
            db.dumps(card.get("sources", [])),
            now,
            now,
            db.dumps([card["format"]]),
        ),
    )
    used = db.loads(
        conn.execute(
            "SELECT formats FROM stories WHERE story_key = ?", (acc.story_key,)
        ).fetchone()["formats"]
    )
    if card["format"] not in used:
        conn.execute(
            "UPDATE stories SET formats = ? WHERE story_key = ?",
            (db.dumps([*used, card["format"]]), acc.story_key),
        )
