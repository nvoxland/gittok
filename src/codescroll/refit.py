"""Rewrite stored cards that no longer fit the card front (validator._check_fit).

`export` writes one JSON file per card that fails the check; an agent shortens the files;
`apply` validates each rewrite like a submission and replaces the card in place, so its id,
events, likes, and saves stay attached.
"""

from __future__ import annotations

import json
from pathlib import Path

from codescroll import db, signals, store, validator


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
        row = conn.execute("SELECT spec, status FROM cards WHERE id = ?", (card_id,)).fetchone()
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
        )
        if rejects:
            r = rejects[0]
            rejected.append({"card_id": card_id, "reason": r.reason, "detail": r.detail})
            continue
        _replace(conn, card_id, accepted[0], old, row["status"])
        replaced.append(card_id)
    return {"replaced": replaced, "rejected": rejected}


def _replace(conn, card_id: str, acc, old: dict, status: str) -> None:
    card = acc.card
    redraw = card["visual"]["kind"] in store.RENDERED_KINDS and card["visual"] != old["visual"]
    with conn:
        conn.execute(
            "UPDATE cards SET format = ?, persona = ?, tone = ?, spec = ?, resolved = ?, "
            "status = ? WHERE id = ?",
            (
                card["format"],
                card["persona"],
                card["tone"],
                db.dumps(card),
                db.dumps(acc.resolved),
                "pending_render" if redraw else status,
                card_id,
            ),
        )
        store.set_features(conn, card_id, card)
