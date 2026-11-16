# ruff: noqa: F811
"""Review fixes in steering.py: rules that do nothing are refused; familiarity history."""

import json
from datetime import timedelta

import pytest

from gittok import learning, steering
from tests.test_steering import NOW, add_card, cfg, conn  # noqa: F401  (fixtures)


@pytest.mark.parametrize("kw", [
    dict(type="limit", feature="persona", value="x", max_share=0.1),
    dict(type="limit", feature="dir", value="src", max_share=0.1),
    dict(type="limit", feature="group", value="g", max_share=0.1),
    dict(type="limit", feature="angle", value="why", max_share=0.1),
    dict(type="boost", feature="language", value="python"),
    dict(type="boost", feature="persona", value="x"),
    dict(type="prefer", feature="kind", value="test"),
    dict(type="prefer", feature="file", value="a.py"),
    dict(type="boost", feature="tag", value="smell"),
    dict(type="focus", feature="angle", value="why", slots=2),
])
def test_a_rule_that_the_brief_ignores_is_refused_with_the_supported_list(conn, cfg, kw):
    with pytest.raises(steering.SteeringError) as e:
        steering.add_rule(conn, cfg, **kw)
    assert "supported" in str(e.value).lower() or "works on" in str(e.value).lower()


@pytest.mark.parametrize("kw", [
    dict(type="limit", feature="format", value="meme", max_share=0.1),
    dict(type="limit", feature="tone", value="roast", max_share=0),
    dict(type="boost", feature="angle", value="why"),
    dict(type="prefer", feature="dir", value="src"),
    dict(type="focus", feature="dir", value="src", slots=2),
])
def test_a_rule_that_the_brief_honors_is_stored(conn, cfg, kw):
    assert steering.add_rule(conn, cfg, **kw)["id"]


def test_familiarity_history_comes_from_the_features_saved_at_the_impression(conn, cfg):
    card = add_card(conn, cfg, format="meme")
    ts = int((NOW - timedelta(days=1)).timestamp() * 1000)
    feats = {("familiarity", "new"), ("format", "meme")}
    for reward in (0.9, 0.2, 0.8):
        cur = conn.execute(
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{}', 'x')", (card, ts))
        conn.execute(
            "INSERT INTO rewards(card_id, impression_event_id, reward, features, computed_at) "
            "VALUES (?, ?, ?, ?, '2026-06-01T00:00:00Z')",
            (card, cur.lastrowid, reward, json.dumps(sorted(feats))))
        model = learning.Model.load(conn, cfg, NOW)
        model.update(feats, reward, 1.0, NOW)
        model.save(conn)
    conn.commit()
    (row,) = [r for r in steering.explain_weights(conn, cfg, feature="familiarity", now=NOW)
              if r["value"] == "new"]
    assert row["impressions"] == 3 and row["hit_rate"] == round(2 / 3, 4)
