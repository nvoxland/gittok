"""Per-rule outcomes: what the scout and the reader said about each detector's candidates.

A rule is a profile detector id. Built-in miners have no rule id, so each built-in tag is
reported as a pseudo-rule `builtin:<tag>` for comparison (docs/learning.md, section 12).

Trace from a card to its rule, exact and without a new column:
`cards.lead_id -> leads.lead_key = "cand:<path>:<start>:<tag>" -> candidates(repo, path,
line_start, tag).rule_id`. Cards whose candidate is gone (a refresh dropped it) are not counted.

Effective weight. `factor = clamp(0.5, 1.5, (K + N x q) / (K + N))` with K = 5 prior points
at neutral (1.0). N = rated windows + cards with a reward. q is the evidence-weighted mean of
two ratios that are 1.0 when "average":
  - scout: mean teachable / 3 (rated windows, N_rated)
  - reader: mean card reward / mean reward of all the repo's cards (N_cards)
A rule with no data has N = 0, so factor = 1.0. The factor scales the candidate's lead strength
in `candidate_leads.leads_for`; `effective_weight(weight, factors, rule)` gives weight x factor.
"""

from __future__ import annotations

from gittok import candidates

PRIOR_K = 5.0
MIN_FACTOR, MAX_FACTOR = 0.5, 1.5
NEUTRAL_TEACHABLE = 3.0


def rule_key(c: dict) -> str:
    return c.get("rule_id") or f"builtin:{c['tag']}"


def _card_rows(conn, repo: str) -> list[dict]:
    """One row per card made from a candidate lead: its key parts, reward and knew/teach counts."""
    rows = conn.execute(
        "SELECT c.id AS card_id, l.lead_key, "
        "(SELECT AVG(reward) FROM rewards w WHERE w.card_id = c.id) AS reward, "
        "(SELECT COUNT(*) FROM knowledge_events k WHERE k.card_id = c.id AND k.kind = 'knew_it') "
        "AS knew_it, "
        "(SELECT COUNT(*) FROM knowledge_events k WHERE k.card_id = c.id "
        "AND k.kind = 'teach_more') AS teach_more "
        "FROM cards c JOIN leads l ON l.id = c.lead_id "
        "WHERE l.repo = ? AND l.lead_key LIKE 'cand:%'",
        (repo,),
    ).fetchall()
    return [dict(r) for r in rows]


def _repo_mean_reward(conn, repo: str) -> float | None:
    row = conn.execute(
        "SELECT AVG(w.reward) FROM rewards w JOIN cards c ON c.id = w.card_id "
        "JOIN repos r ON r.id = c.repo_id WHERE r.name = ?",
        (repo,),
    ).fetchone()
    return row[0]


def factor_for(
    n_rated: int, mean_teachable: float | None, n_cards: int, rel_reward: float | None
) -> float:
    """The outcome factor for one rule. 1.0 when there is no data."""
    parts = []
    if n_rated and mean_teachable is not None:
        parts.append((n_rated, mean_teachable / NEUTRAL_TEACHABLE))
    if n_cards and rel_reward is not None:
        parts.append((n_cards, rel_reward))
    n = sum(w for w, _ in parts)
    if not n:
        return 1.0
    q = sum(w * v for w, v in parts) / n
    return max(MIN_FACTOR, min(MAX_FACTOR, (PRIOR_K + n * q) / (PRIOR_K + n)))


def rollup(conn, repo: str) -> list[dict]:
    """One row per rule (profile detector or `builtin:<tag>`), most useful first."""
    cands = candidates.load_candidates(conn, repo)
    by_cand = {(c["path"], c["start"], c["tag"]): rule_key(c) for c in cands}
    stats: dict[str, dict] = {}

    def row(rule: str) -> dict:
        return stats.setdefault(
            rule,
            {
                "rule": rule,
                "found": 0,
                "rated": 0,
                "_teach": 0,
                "cards": 0,
                "_reward": 0.0,
                "_rewarded": 0,
                "knew_it": 0,
                "teach_more": 0,
            },
        )

    for c in cands:
        row(rule_key(c))["found"] += 1
    for r in candidates.load_rated(conn, repo):
        s = row(rule_key(r))
        s["rated"] += 1
        s["_teach"] += r["teachable"]
    for cr in _card_rows(conn, repo):
        try:
            path, start, tag = cr["lead_key"][len("cand:") :].rsplit(":", 2)
            rule = by_cand.get((path, int(start), tag))
        except ValueError:
            rule = None
        if rule is None:
            continue
        s = row(rule)
        s["cards"] += 1
        s["knew_it"] += cr["knew_it"]
        s["teach_more"] += cr["teach_more"]
        if cr["reward"] is not None:
            s["_reward"] += cr["reward"]
            s["_rewarded"] += 1
    mean_all = _repo_mean_reward(conn, repo)
    out = []
    for s in stats.values():
        mean_t = s["_teach"] / s["rated"] if s["rated"] else None
        mean_r = s["_reward"] / s["_rewarded"] if s["_rewarded"] else None
        rel = mean_r / mean_all if mean_r is not None and mean_all else None
        out.append(
            {
                "rule": s["rule"],
                "found": s["found"],
                "rated": s["rated"],
                "mean_teachable": None if mean_t is None else round(mean_t, 2),
                "cards": s["cards"],
                "mean_reward": None if mean_r is None else round(mean_r, 4),
                "knew_it": s["knew_it"],
                "teach_more": s["teach_more"],
                "factor": round(factor_for(s["rated"], mean_t, s["_rewarded"], rel), 4),
            }
        )
    out.sort(key=lambda r: (-r["factor"], -r["cards"], -r["found"], r["rule"]))
    return out


WEAK_FACTOR = 0.8  # under this, the scout or the reader says the rule finds poor windows


def weak_rules(conn, repo: str, rule_ids) -> list[str]:
    """The rules of `rule_ids` (the detector ids of the repo's profile) whose factor is under
    WEAK_FACTOR. A factor that low needs data: with the neutral prior, at least 3 windows that
    the scout rated 1, or more evidence that is less bad."""
    keep = set(rule_ids)
    rows = rollup(conn, repo)
    return sorted(r["rule"] for r in rows if r["rule"] in keep and r["factor"] < WEAK_FACTOR)


def factors(conn, repo: str) -> dict[str, float]:
    """Rule key -> outcome factor (0.5 to 1.5), for every rule that has a current candidate."""
    return {r["rule"]: r["factor"] for r in rollup(conn, repo)}


def effective_weight(weight: float, factor_map: dict[str, float], rule: str) -> float:
    """A rule's profile weight scaled by its outcome. Unknown rule: the weight stays."""
    return weight * factor_map.get(rule, 1.0)
