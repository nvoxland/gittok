import json
import math
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from gittok import db, learning, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
T0 = int((NOW - timedelta(hours=2)).timestamp() * 1000)
MIN = 60_000
LIKE = learning.default_reward_config().like_floor  # a liked card scores at least this


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    c.execute(
        "INSERT INTO runs(id, status, started_at) VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
    )
    yield c
    c.close()


def add_card(conn, cfg, spec=None, created_at="2026-05-31T00:00:00Z", **over) -> str:
    spec = spec or text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), **over)
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now=created_at)
    conn.commit()
    return cid


def ev(conn, card, type_, ts, data=None, session="s1") -> int:
    d = dict(data or {})
    if session:
        d["session"] = session
    cur = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, ?)",
        (card, type_, ts, json.dumps(d), "2026-06-01T00:00:00Z"),
    )
    conn.commit()
    return cur.lastrowid


def at(minutes: float) -> datetime:
    """Wall-clock time `minutes` after T0."""
    return datetime.fromtimestamp(T0 / 1000 + minutes * 60, UTC)


def rewards(conn):
    return {r["card_id"]: r["reward"] for r in conn.execute("SELECT * FROM rewards")}


def test_dwell_reward_for_closed_impression(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    spec = json.loads(conn.execute("SELECT spec FROM cards WHERE id=?", (a,)).fetchone()[0])
    exp = learning.expected_ms(learning.load_reward_config(cfg), spec)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dwell", T0 + 500, {"ms": exp // 2})
    ev(conn, b, "impression", T0 + 1000)
    res = learning.process_events(conn, cfg, now=at(5))
    assert res["impressions"] == 1 and res["rewards"] == 1
    assert rewards(conn)[a] == pytest.approx(0.45 * (exp // 2) / exp)


def test_skip_is_zero_even_with_other_signals(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "skip", T0 + 300, {"ms": 300})
    ev(conn, a, "depth_open", T0 + 400, {"panel": 1})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn)[a] == 0.0


@pytest.mark.parametrize("positive", ["like", "save"])
def test_explicit_like_or_save_beats_skip(conn, cfg, positive):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "skip", T0 + 300, {"ms": 300})
    ev(conn, a, positive, T0 + 400, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    rc = learning.default_reward_config()
    want = rc.like_floor if positive == "like" else rc.weights[positive]
    assert rewards(conn)[a] == pytest.approx(want)


def test_process_events_updates_story_best_reward_and_liked(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "like", T0 + 400, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    ev(conn, b, "like", T0 + 1100, {"on": True})
    ev(conn, b, "like", T0 + 1200, {"on": False})
    learning.process_events(conn, cfg, now=at(5))

    def story(card):
        return conn.execute(
            "SELECT s.best_reward, s.liked FROM stories s JOIN cards c USING (story_key) "
            "WHERE c.id = ?",
            (card,),
        ).fetchone()

    assert story(a)["liked"] == 1
    assert story(a)["best_reward"] == pytest.approx(rewards(conn)[a])
    assert story(b)["liked"] == 0
    # a later, lower reward does not lower best_reward
    ev(conn, a, "impression", T0 + 10 * MIN)
    ev(conn, a, "skip", T0 + 10 * MIN + 100, {"ms": 100})
    ev(conn, b, "impression", T0 + 20 * MIN)
    learning.process_events(conn, cfg, now=at(60))
    assert story(a)["best_reward"] == pytest.approx(LIKE)


def test_short_dwell_without_engagement_counts_as_skip(conn, cfg):
    a, b, c = add_card(conn, cfg), add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dwell", T0 + 500, {"ms": 500})  # no skip event from the client
    ev(conn, b, "impression", T0 + 1000)
    ev(conn, b, "dwell", T0 + 1500, {"ms": 500})
    ev(conn, b, "depth_open", T0 + 1600, {"panel": 1})
    ev(conn, c, "impression", T0 + 2000)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn)[a] == 0.0
    assert rewards(conn)[b] > 0.15


@pytest.mark.parametrize("bad", ["abc", None, -5, 1e12, [1], {"x": 1}, float("inf")])
def test_malformed_ms_does_not_stop_learning(conn, cfg, bad):
    a, b, c = add_card(conn, cfg), add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dwell", T0 + 500, {"ms": bad})
    ev(conn, b, "impression", T0 + 1000)
    ev(conn, b, "dwell", T0 + 1500, {"ms": 10**6})
    ev(conn, c, "impression", T0 + 2000)
    res = learning.process_events(conn, cfg, now=at(5))
    assert res["rewards"] == 2
    r = rewards(conn)
    assert 0.0 <= r[a] <= 1.0
    assert r[b] == pytest.approx(0.45)


def test_non_dict_event_data_is_ignored(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'dwell', ?, '[1]', 'x')",
        (a, T0 + 100),
    )
    ev(conn, a, "like", T0 + 200, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    assert learning.process_events(conn, cfg, now=at(5))["rewards"] == 1
    assert rewards(conn)[a] == pytest.approx(LIKE)


def test_engagement_sums_and_clips_to_one(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dwell", T0 + 9000, {"ms": 10**6})
    for t, d in [
        ("depth_open", {"panel": 1}),
        ("depth_open", {"panel": 2}),
        ("like", {"on": True}),
        ("save", {"on": True}),
        ("scroll_back", {}),
    ]:
        ev(conn, a, t, T0 + 9500, d)
    ev(conn, b, "impression", T0 + 10_000)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn)[a] == 1.0


def test_depth_open_counts_once_and_like_toggle_off_does_not_count(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "depth_open", T0 + 100, {"panel": 1})
    ev(conn, a, "depth_open", T0 + 200, {"panel": 2})
    ev(conn, a, "like", T0 + 300, {"on": True})
    ev(conn, a, "like", T0 + 400, {"on": False})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn)[a] == pytest.approx(0.15)


def test_lightbox_open_counts_once_with_the_depth_open_weight(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "lightbox_open", T0 + 100, {"kind": "code"})
    ev(conn, a, "lightbox_open", T0 + 200, {"kind": "code"})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn)[a] == pytest.approx(0.15)


def test_open_window_is_not_scored_until_next_impression_or_30_minutes(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    assert learning.process_events(conn, cfg, now=at(29))["rewards"] == 0
    assert learning.process_events(conn, cfg, now=at(31))["rewards"] == 1
    ev(conn, b, "impression", T0 + 40 * MIN)
    assert learning.process_events(conn, cfg, now=at(41))["rewards"] == 0
    assert set(rewards(conn)) == {a}


def test_window_is_capped_at_30_minutes(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "like", T0 + 40 * MIN, {"on": True})
    ev(conn, b, "impression", T0 + 50 * MIN)
    learning.process_events(conn, cfg, now=at(60))
    assert rewards(conn)[a] == 0.0


def test_session_window_ends_at_next_impression_of_any_card(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0, session="s1")
    ev(conn, b, "impression", T0 + 2000, session="s1")
    ev(conn, a, "like", T0 + 5000, {"on": True}, session="s1")  # after a's window closed
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn) == {a: 0.0}


def test_other_sessions_do_not_close_a_window(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0, session="s1")
    ev(conn, b, "impression", T0 + 2000, session="s2")
    ev(conn, a, "like", T0 + 5000, {"on": True}, session="s1")
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn) == {}


def test_events_without_session_group_by_card(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0, session=None)
    ev(conn, b, "impression", T0 + 2000, session=None)
    ev(conn, a, "like", T0 + 5000, {"on": True}, session=None)
    ev(conn, a, "impression", T0 + 10_000, session=None)
    learning.process_events(conn, cfg, now=at(5))
    assert rewards(conn) == {a: pytest.approx(LIKE)}


def test_process_events_is_idempotent(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, b, "impression", T0 + 1000)
    first = learning.process_events(conn, cfg, now=at(5))
    snapshot = [tuple(r) for r in conn.execute("SELECT * FROM model_weights")]
    second = learning.process_events(conn, cfg, now=at(6))
    assert first["rewards"] == 1 and second == {"impressions": 0, "rewards": 0, "weights": 0}
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    assert [tuple(r) for r in conn.execute("SELECT * FROM model_weights")] == snapshot


def test_expected_ms_uses_default_for_unknown_format_and_caps():
    rc = learning.default_reward_config()
    spec = {"format": "mystery", "hook": "one two", "visual": {"kind": "text", "body": "a b c"}}
    assert learning.expected_ms(rc, spec) == 2500 + 250 * 5
    spec["hook"] = "w " * 1000
    assert learning.expected_ms(rc, spec) == 45000


def test_reward_config_defaults_file_overrides_and_unknown_keys(cfg, tmp_path):
    assert learning.load_reward_config(cfg).weights["save"] == 0.30
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reward.yaml").write_text("weights:\n  save: 0.5\nhalf_life_days: 7\n")
    rc = learning.load_reward_config(cfg)
    assert rc.weights["save"] == 0.5 and rc.weights["like"] == 0.25 and rc.half_life_days == 7
    (tmp_path / "config" / "reward.yaml").write_text("weights: 3\n")
    with pytest.raises(learning.RewardConfigError):
        learning.load_reward_config(cfg)


def test_unknown_reward_key_is_dropped_with_a_warning_and_the_file_still_loads(cfg, tmp_path):
    """A running process may read a newer reward file: an unknown key must not stop it."""
    from gittok.config import load_config

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reward.yaml").write_text(
        "future: 1\nweights:\n  nope: 1\n  save: 0.5\n"
    )
    rc = learning.load_reward_config(cfg)
    assert rc.weights["save"] == 0.5 and "nope" not in rc.weights
    assert not hasattr(rc, "future")
    warnings = load_config(cfg.root, shared=cfg.root).warnings
    for key in ("'future'", "'weights.nope'"):
        assert any(key in w and "config/reward.yaml" in w for w in warnings), (key, warnings)
    assert len(warnings) == 2


def test_shipped_reward_file_has_no_unknown_keys():
    """Typos in the shipped file must not hide behind the warning."""
    from gittok import config

    assert learning.reward_warnings(config.shipped_root()) == ()


def weights(conn):
    return {
        (r["feature"], r["value"]): (r["mean"], r["precision"], r["n"])
        for r in conn.execute("SELECT * FROM model_weights")
    }


def liked_impression(conn, card, other, t=0, session="s1"):
    ev(conn, card, "impression", T0 + t, session=session)
    ev(conn, card, "like", T0 + t + 100, {"on": True}, session=session)
    ev(conn, other, "impression", T0 + t + 1000, session=session)


def test_card_features_include_stored_group_and_recency(conn, cfg):
    import dataclasses

    repo = dataclasses.replace(cfg.repos["fixture"], group="work")
    cfg = dataclasses.replace(cfg, repos={"fixture": repo})
    now = datetime(2026, 6, 1, tzinfo=UTC)
    new = add_card(conn, cfg, created_at="2026-05-30T00:00:00Z")
    recent = add_card(conn, cfg, created_at="2026-05-10T00:00:00Z")
    old = add_card(conn, cfg, created_at="2026-01-01T00:00:00Z")
    feats = dict(learning.card_features(conn, cfg, new, now=now))
    assert feats["story_type"] == "rip" and feats["tone"] == "wholesome-nerdy"
    assert feats["repo"] == "fixture" and feats["group"] == "work" and feats["recency"] == "new"
    assert dict(learning.card_features(conn, cfg, recent, now=now))["recency"] == "recent"
    assert dict(learning.card_features(conn, cfg, old, now=now))["recency"] == "old"


def model(conn, cfg, now=NOW):
    return learning.Model.load(conn, cfg, now)


def test_a_liked_card_raises_its_weights_and_their_certainty(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    liked_impression(conn, a, b)
    res = learning.process_events(conn, cfg, now=at(5))
    w = weights(conn)
    m = model(conn, cfg, at(5))
    for key in [learning.BIAS, ("persona", "archivist"), ("tone", "wholesome-nerdy")]:
        m0, q0 = m.prior(key)
        assert w[key][0] > m0 and w[key][1] > q0, key
        assert w[key][2] == pytest.approx(learning.default_reward_config().like_weight)
    assert res["weights"] == len(w) >= 8
    assert {r[0] for r in conn.execute("SELECT DISTINCT updated_at FROM model_weights")} == {
        learning._iso(at(5))
    }


def test_the_reward_snapshot_keeps_the_features_and_the_familiarity(conn, cfg):
    a, b = add_card(conn, cfg, dirs=["src/app"]), add_card(conn, cfg)
    liked_impression(conn, a, b)
    learning.process_events(conn, cfg, now=at(5))
    row = conn.execute("SELECT * FROM rewards WHERE card_id = ?", (a,)).fetchone()
    feats = {tuple(k) for k in json.loads(row["features"])}
    assert ("familiarity", "new") in feats and ("dir", "src/app") in feats
    assert row["signal"] == "like"


def test_familiarity_buckets():
    assert [learning.familiarity(n) for n in (1.0, 0.7, 0.5, 0.35, 0.1)] == [
        "new",
        "new",
        "some",
        "some",
        "known",
    ]


def test_a_cross_of_angle_and_familiarity_is_learned_on_its_own(conn, cfg):
    m = model(conn, cfg)
    x = m.expand({("angle", "why"), ("familiarity", "known"), ("format", "meme")})
    assert x[learning.cross_key("angle", "familiarity", "why", "known")] == 1.0
    assert x[learning.BIAS] == 1.0 and len(x) == 5


def test_story_type_prior_follows_category_share(conn, cfg):
    from gittok import brief

    types = {t for ts in brief.CATEGORY_STORIES.values() for t in ts}
    share = {t: learning._mix_share(cfg, "story_type", t)[0] for t in types}
    hi, lo = max(share, key=share.get), min(share, key=share.get)
    assert share[hi] > share[lo]
    m = model(conn, cfg)
    assert m.prior(("story_type", hi))[0] > m.prior(("story_type", lo))[0]
    assert m.prior(("persona", "archivist"))[0] == 0.0


def test_evidence_decays_toward_the_prior_with_the_half_life(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    liked_impression(conn, a, b)
    learning.process_events(conn, cfg, now=at(5))
    key = ("persona", "archivist")
    fresh = model(conn, cfg, at(5)).state(key)
    later = model(conn, cfg, at(5) + timedelta(days=21)).state(key)
    m0, q0 = model(conn, cfg).prior(key)
    assert later[0] - m0 == pytest.approx((fresh[0] - m0) / 2)
    assert later[1] - q0 == pytest.approx((fresh[1] - q0) / 2)
    assert later[2] == pytest.approx(fresh[2] / 2)


def test_posterior_means_read_only_and_decay_lazily(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    liked_impression(conn, a, b)
    learning.process_events(conn, cfg, now=at(5))
    before = weights(conn)
    fresh = learning.posterior_means(conn, cfg, "persona", now=at(5))["archivist"]
    assert fresh[0] > 0.5 and fresh[1] == pytest.approx(2.0)
    old = learning.posterior_means(conn, cfg, "persona", now=at(5) + timedelta(days=400))
    assert old["archivist"][0] == pytest.approx(0.5, abs=0.01) and old["archivist"][1] < 0.01
    assert weights(conn) == before


def put_weight(conn, cfg, feature, value, good, bad, when=NOW):
    """A stored weight as if `good` rewards of 1 and `bad` rewards of 0 were seen."""
    m = learning.Model(cfg, learning.load_reward_config(cfg), {}, when)
    m0, q0 = m.prior((feature, value))
    conn.execute(
        "INSERT OR REPLACE INTO model_weights VALUES (?, ?, ?, ?, ?, ?)",
        (
            feature,
            value,
            m0 + math.log((good + 1) / (bad + 1)),
            q0 + (good + bad) / 4,
            good + bad,
            learning._iso(when),
        ),
    )
    conn.commit()


def test_score_cards_is_seeded_bounded_and_does_not_write(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg, persona="greybeard")
    s1 = learning.score_cards(conn, cfg, [a, b], random.Random(7), now=NOW)
    s2 = learning.score_cards(conn, cfg, [a, b], random.Random(7), now=NOW)
    assert s1 == s2 and set(s1) == {a, b} and all(0 < v < 1 for v in s1.values())
    assert learning.score_cards(conn, cfg, [a, b], random.Random(8), now=NOW) != s1
    assert weights(conn) == {}


def test_a_draw_scores_the_same_in_any_order(conn, cfg):
    feats = [{("format", "meme"), ("tone", "roast")}, {("format", "chart"), ("tone", "roast")}]
    m = model(conn, cfg)
    one, two = m.draw(random.Random(5)), m.draw(random.Random(5))
    assert [one.logit(f) for f in feats] == [two.logit(f) for f in reversed(feats)][::-1]


def test_score_cards_prefers_features_with_good_evidence(conn, cfg):
    good = add_card(conn, cfg, persona="archivist")
    bad = add_card(conn, cfg, persona="greybeard")
    put_weight(conn, cfg, "persona", "archivist", good=40, bad=2)
    put_weight(conn, cfg, "persona", "greybeard", good=2, bad=40)
    wins = 0
    for seed in range(30):
        s = learning.score_cards(conn, cfg, [good, bad], random.Random(seed), now=NOW)
        wins += s[good] > s[bad]
    assert wins >= 28


def test_score_cards_ignores_unknown_card_ids(conn, cfg):
    assert learning.score_cards(conn, cfg, ["nope"], random.Random(1), now=NOW) == {}


def test_reset_weights_all_or_one_feature(conn, cfg):
    put_weight(conn, cfg, "persona", "archivist", 1, 1)
    put_weight(conn, cfg, "persona", "greybeard", 1, 1)
    put_weight(conn, cfg, "tone", "roast", 1, 1)
    assert learning.reset_weights(conn, "persona") == 2
    assert set(weights(conn)) == {("tone", "roast")}
    assert learning.reset_weights(conn) == 1
    assert learning.reset_weights(conn) == 0


def test_the_model_finds_the_feature_that_explains_the_dislikes(cfg):
    """Credit assignment: memes get 👎 and charts get likes, both spread over the same dirs.
    The format weights must take the blame and the credit; the dirs stay near neutral."""
    rc = learning.load_reward_config(cfg)
    m = learning.Model(cfg, rc, {}, NOW)
    for i in range(30):
        d = ("dir", f"d{i % 3}")
        m.update({("format", "meme"), d}, 0.0, rc.dislike_weight, NOW)
        m.update({("format", "chart"), d}, rc.like_floor, rc.like_weight, NOW)
    meme, chart = m.effect(("format", "meme")), m.effect(("format", "chart"))
    assert meme < -1 and chart > 1
    assert all(abs(m.effect(("dir", f"d{i}"))) < 0.25 * min(-meme, chart) for i in range(3))


def test_a_dislike_moves_the_model_more_than_a_plain_skip(cfg):
    rc = learning.load_reward_config(cfg)
    skip, down = (learning.Model(cfg, rc, {}, NOW) for _ in range(2))
    skip.update({("format", "meme")}, 0.0, 1.0, NOW)
    down.update({("format", "meme")}, 0.0, rc.dislike_weight, NOW)
    assert down.effect(("format", "meme")) < skip.effect(("format", "meme")) < 0


def test_relearn_rebuilds_the_same_model_from_the_rewards(conn, cfg):
    a, b, c = add_card(conn, cfg), add_card(conn, cfg, persona="greybeard"), add_card(conn, cfg)
    liked_impression(conn, a, b)
    ev(conn, b, "dislike", T0 + 1100, {"on": True})
    ev(conn, c, "impression", T0 + 2000)
    learning.process_events(conn, cfg, now=at(5))
    online = weights(conn)
    assert learning.relearn(conn, cfg, now=at(5)) == 2
    assert weights(conn).keys() == online.keys()
    for key, row in weights(conn).items():
        assert row == pytest.approx(online[key]), key


def default_shares(cfg):
    return cfg.defaults["categories"]


def test_category_shares_equal_default_mix_without_data(conn, cfg):
    shares = learning.category_shares(conn, cfg, now=NOW)
    assert shares == pytest.approx(default_shares(cfg))


def code_evidence(conn, cfg, good, bad, when=NOW):
    from gittok import brief

    # Only formats that no other category lists, so other categories see no shared evidence.
    for f in brief.CATEGORY_FORMATS["code"]:
        if f != "code_card":
            put_weight(conn, cfg, "format", f, good, bad, when)


def test_category_shares_move_toward_better_rewarded_categories(conn, cfg):
    code_evidence(conn, cfg, good=45, bad=5)
    from gittok import brief

    for f in brief.CATEGORY_FORMATS["memes"]:
        put_weight(conn, cfg, "format", f, 5, 45)
    shares = learning.category_shares(conn, cfg, now=NOW)
    base = default_shares(cfg)
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares["code"] > base["code"] and shares["memes"] < base["memes"]


def test_more_evidence_moves_shares_further(conn, cfg):
    from gittok import brief

    for f in brief.CATEGORY_FORMATS["memes"]:
        put_weight(conn, cfg, "format", f, 5, 5)
    code_evidence(conn, cfg, good=9, bad=1)
    small = learning.category_shares(conn, cfg, now=NOW)["code"]
    code_evidence(conn, cfg, good=90, bad=10)
    large = learning.category_shares(conn, cfg, now=NOW)["code"]
    assert large > small > default_shares(cfg)["code"]


def test_category_shares_never_drop_below_floor(conn, cfg):
    from gittok import brief

    code_evidence(conn, cfg, good=0, bad=5000)
    for f in brief.CATEGORY_FORMATS["memes"]:
        put_weight(conn, cfg, "format", f, 5000, 0)
    shares = learning.category_shares(conn, cfg, now=NOW)
    assert min(shares.values()) >= 0.05 - 1e-9
    assert shares["code"] == pytest.approx(0.05)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_category_with_default_share_zero_stays_zero(conn, cfg):
    cfg.defaults["categories"] = {**cfg.defaults["categories"], "interactive": 0.0}
    shares = learning.category_shares(conn, cfg, now=NOW)
    assert shares["interactive"] == 0.0
    assert sum(shares.values()) == pytest.approx(1.0)
    from gittok import brief

    code_evidence(conn, cfg, good=0, bad=5000)
    for f in brief.CATEGORY_FORMATS["memes"]:
        put_weight(conn, cfg, "format", f, 5000, 0)
    shares = learning.category_shares(conn, cfg, now=NOW)
    assert shares["interactive"] == 0.0
    assert shares["code"] == pytest.approx(0.05)
    assert sum(shares.values()) == pytest.approx(1.0)


# Video-style signals for beat cards.

BEAT_SPEC = {"format": "group_chat", "hook": "h", "visual": {}, "depth": []}


def beat_reward(*events):
    return learning._reward(learning.default_reward_config(), BEAT_SPEC, list(events))


def test_beat_card_reward_is_watch_fraction_by_time_played_not_dwell():
    # 20 s on screen, but only half of the 6 s sequence played: after playback is not credit.
    r = beat_reward(("dwell", {"ms": 20000, "ms_played": 3000, "total_ms": 6000}))
    assert r == pytest.approx(0.45 * 0.5)


def test_watch_fraction_adds_up_across_visits():
    r = beat_reward(
        ("dwell", {"ms": 2000, "ms_played": 2000, "total_ms": 8000}),
        ("dwell", {"ms": 2500, "ms_played": 2000, "total_ms": 8000}),
    )
    assert r == pytest.approx(0.45 * 0.5)


def test_completion_and_one_replay_add_their_weights():
    full = ("dwell", {"ms": 7000, "ms_played": 6000, "total_ms": 6000})
    assert beat_reward(full, ("beats_done", {"beats": 4})) == pytest.approx(0.45 + 0.15)
    with_replays = beat_reward(full, ("replay", {}), ("replay", {}))
    assert with_replays == pytest.approx(0.45 + 0.30)  # a replay counts once


def test_beat_tap_is_recorded_but_not_rewarded():
    played = ("dwell", {"ms": 3000, "ms_played": 3000, "total_ms": 6000})
    assert beat_reward(played, ("beat_tap", {"beat": 1})) == beat_reward(played)


def test_early_swipe_on_a_beat_card_is_a_skip():
    r = beat_reward(("dwell", {"ms": 1500, "ms_played": 1500, "total_ms": 6000}), ("skip", {}))
    assert r == 0.0


def test_format_factors_empty_without_evidence(conn, cfg):
    assert learning.format_factors(conn, cfg, now=NOW) == {}


def test_format_factors_favor_better_rewarded_formats(conn, cfg):
    put_weight(conn, cfg, "format", "meme", 12, 4)
    put_weight(conn, cfg, "format", "chart", 4, 12)
    f = learning.format_factors(conn, cfg, now=NOW)
    assert set(f) == {"meme", "chart"}
    assert f["meme"] > 1 > f["chart"]
    put_weight(conn, cfg, "format", "meme", 40, 10)
    assert learning.format_factors(conn, cfg, now=NOW)["meme"] > f["meme"]


def test_dir_prefixes_share_one_unit_of_input(conn, cfg):
    deep = add_card(conn, cfg, dirs=["a/b/c/d"])
    feats = learning.card_features(conn, cfg, deep, now=NOW)
    x = model(conn, cfg).expand(feats)
    dirs = [v for k, v in x.items() if k[0] == "dir"]
    assert len(dirs) == 4 and sum(dirs) == pytest.approx(1.0)


def test_reward_updates_every_prefix(conn, cfg):
    a, b = add_card(conn, cfg, dirs=["x/y/z"]), add_card(conn, cfg)
    liked_impression(conn, a, b)
    learning.process_events(conn, cfg, now=at(5))
    w = weights(conn)
    assert {v for (f, v) in w if f == "dir"} >= {"x", "x/y", "x/y/z"}


def test_lead_mean_reward_updates(conn, cfg):
    conn.execute(
        "INSERT INTO leads(id, repo, story_type, kind, lead_key, text, strength, head_sha, "
        "first_seen_at, last_seen_at) VALUES (1, 'fixture', 'rip', 'path', 'p:x', 't', 1.0, 'h', "
        "'x', 'x')"
    )
    a, b, plain = add_card(conn, cfg), add_card(conn, cfg), add_card(conn, cfg)
    conn.execute("UPDATE cards SET lead_id = 1 WHERE id IN (?, ?)", (a, b))
    conn.commit()
    ev(conn, a, "impression", T0)
    ev(conn, a, "like", T0 + 400, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    ev(conn, b, "skip", T0 + 1100, {"ms": 100})
    ev(conn, plain, "impression", T0 + 2000)
    learning.process_events(conn, cfg, now=at(5))
    got = conn.execute("SELECT mean_reward, rewards_n FROM leads WHERE id = 1").fetchone()
    r = rewards(conn)
    assert got["rewards_n"] == 2
    assert got["mean_reward"] == pytest.approx((r[a] + r[b]) / 2)
    assert r[a] != r[b]
    # processing again changes nothing
    learning.process_events(conn, cfg, now=at(6))
    assert conn.execute("SELECT rewards_n FROM leads WHERE id = 1").fetchone()[0] == 2


def test_reward_defaults_live_only_in_the_shipped_yaml():
    """config/reward.yaml is the one source of the defaults: the dataclass holds none."""
    from pathlib import Path

    import yaml

    with pytest.raises(TypeError):
        learning.RewardConfig()
    shipped = yaml.safe_load((Path(__file__).parents[1] / "config" / "reward.yaml").read_text())
    rc = learning.default_reward_config()
    assert set(shipped) == set(learning.RewardConfig.__dataclass_fields__)
    for key, value in shipped.items():
        assert getattr(rc, key) == value, key


def test_reward_config_is_parsed_once_until_the_file_changes(cfg, tmp_path, monkeypatch):
    import os

    file = tmp_path / "config" / "reward.yaml"
    file.parent.mkdir()
    file.write_text("half_life_days: 7\n")
    reads = []
    from gittok import overlay

    real = overlay.yaml.safe_load
    monkeypatch.setattr(overlay.yaml, "safe_load", lambda t: reads.append(1) or real(t))
    assert learning.load_reward_config(cfg).half_life_days == 7
    first = len(reads)
    assert first >= 1
    assert learning.load_reward_config(cfg).half_life_days == 7
    assert len(reads) == first
    file.write_text("half_life_days: 9\n")
    os.utime(file, ns=(1, 1))  # a new mtime, whatever the clock resolution
    assert learning.load_reward_config(cfg).half_life_days == 9
    assert len(reads) > first
    file.unlink()
    assert learning.load_reward_config(cfg).half_life_days == 21  # the shipped default


def test_reward_slotting_knobs_merge_over_the_shipped_ones(cfg, tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reward.yaml").write_text("slotting:\n  repeat_days: 3\n")
    knobs = learning.load_reward_config(cfg).slotting
    assert knobs["repeat_days"] == 3 and knobs["max_srs_per_batch"] == 2


# ---------------------------------------------------------------- thumbs up and down


def reward_rows(conn):
    return {r["card_id"]: (r["reward"], r["weight"]) for r in conn.execute("SELECT * FROM rewards")}


def test_dislike_is_zero_reward_with_a_heavy_weight(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dwell", T0 + 500, {"ms": 60_000})
    ev(conn, a, "depth_open", T0 + 600, {"panel": 1})
    ev(conn, a, "dislike", T0 + 700, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    rc = learning.default_reward_config()
    assert reward_rows(conn)[a] == (0.0, rc.dislike_weight)
    assert rc.dislike_weight > rc.like_weight > 1


def test_dislike_toggled_off_counts_as_a_plain_impression(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "depth_open", T0 + 600, {"panel": 1})
    ev(conn, a, "dislike", T0 + 700, {"on": True})
    ev(conn, a, "dislike", T0 + 800, {"on": False})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    r, w = reward_rows(conn)[a]
    assert r > 0 and w == 1


def test_like_lifts_the_reward_to_a_floor_with_a_heavier_weight(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "skip", T0 + 300, {"ms": 300})
    ev(conn, a, "like", T0 + 400, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    rc = learning.default_reward_config()
    assert reward_rows(conn)[a] == (pytest.approx(rc.like_floor), rc.like_weight)


def test_a_dislike_marks_the_story_so_no_variant_is_made(conn, cfg):
    from gittok import store

    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dislike", T0 + 400, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    story = conn.execute(
        "SELECT s.* FROM stories s JOIN cards c USING (story_key) WHERE c.id = ?", (a,)
    ).fetchone()
    assert story["disliked"] == 1
    agent = cfg.settings.agent
    assert "👎" in store.variant_blocker(story, "meme", agent, NOW + timedelta(days=400))


def test_old_knew_it_and_teach_more_events_change_nothing(conn, cfg):
    a, b = add_card(conn, cfg), add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "knew_it", T0 + 400, {"on": True})
    ev(conn, a, "teach_more", T0 + 500, {"on": True})
    ev(conn, b, "impression", T0 + 1000)
    learning.process_events(conn, cfg, now=at(5))
    assert reward_rows(conn)[a] == (0.0, 1)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "requests" not in tables


def test_value_factors_favor_the_values_the_reader_likes(conn, cfg):
    assert learning.value_factors(conn, cfg, "tone", now=NOW) == {}
    put_weight(conn, cfg, "tone", "roast", 30, 2)
    put_weight(conn, cfg, "tone", "hype", 2, 30)
    f = learning.value_factors(conn, cfg, "tone", now=NOW)
    assert f["roast"] > 1 > f["hype"]
    assert learning.format_factors(conn, cfg, now=NOW) == learning.value_factors(
        conn, cfg, "format", now=NOW
    )


def test_a_learned_factor_is_clamped(conn, cfg):
    put_weight(conn, cfg, "format", "meme", 900, 0)
    put_weight(conn, cfg, "format", "chart", 0, 900)
    f = learning.format_factors(conn, cfg, now=NOW)
    assert f["meme"] == learning.FACTOR_MAX and f["chart"] == 1 / learning.FACTOR_MAX


def test_a_dislike_closes_its_impression_window_at_once(conn, cfg):
    a = add_card(conn, cfg)
    ev(conn, a, "impression", T0)
    ev(conn, a, "dislike", T0 + 500, {"on": True})
    # No next impression and far under 30 minutes: the 👎 still counts now.
    learning.process_events(conn, cfg, now=at(1))
    assert reward_rows(conn)[a] == (0.0, learning.default_reward_config().dislike_weight)
