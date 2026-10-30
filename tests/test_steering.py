import json
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from codescroll import config as config_mod
from codescroll import db, learning, steering, store
from tests.cards import text_card
from tests.conftest import make_config

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def test_add_boost_rule_defaults_factor_and_persists(conn, cfg):
    rule = steering.add_rule(conn, cfg, type="boost", feature="format", value="meme")
    assert rule["id"] > 0
    assert rule["factor"] == 2.0
    assert rule["created_by"] == "agent"
    row = conn.execute("SELECT * FROM rules WHERE id = ?", (rule["id"],)).fetchone()
    assert (row["type"], row["feature"], row["value"], row["factor"]) == (
        "boost",
        "format",
        "meme",
        2.0,
    )
    json.dumps(rule)


def test_add_rule_rejects_bad_type_feature_and_numbers(conn, cfg):
    cases = [
        (dict(type="nuke", feature="format", value="meme"), "type"),
        (dict(type="ban", feature="colour", value="red"), "feature"),
        (dict(type="boost", feature="format", value="meme", factor=0), "factor"),
        (dict(type="prefer", feature="persona", value="greybeard", factor=-1), "factor"),
        (dict(type="focus", feature="repo", value="fixture"), "slots"),
        (dict(type="focus", feature="repo", value="fixture", slots=11), "slots"),
        (dict(type="limit", feature="tone", value="roast"), "max_share"),
        (dict(type="limit", feature="tone", value="roast", max_share=1.5), "max_share"),
    ]
    for kwargs, word in cases:
        with pytest.raises(steering.SteeringError, match=word):
            steering.add_rule(conn, cfg, **kwargs)
    assert conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0


def test_add_rule_defaults_per_type(conn, cfg):
    prefer = steering.add_rule(conn, cfg, type="prefer", feature="persona", value="greybeard")
    assert prefer["factor"] == 1.5
    ban = steering.add_rule(conn, cfg, type="ban", feature="format", value="horoscope")
    assert (ban["factor"], ban["slots"], ban["max_share"]) == (None, None, None)
    focus = steering.add_rule(conn, cfg, type="focus", feature="repo", value="fixture", slots=5)
    assert focus["slots"] == 5 and focus["factor"] is None
    limit = steering.add_rule(conn, cfg, type="limit", feature="tone", value="roast", max_share=0)
    assert limit["max_share"] == 0


def test_add_rule_checks_values_against_known_ones(conn, cfg):
    with pytest.raises(steering.SteeringError, match="Did you mean 'meme'"):
        steering.add_rule(conn, cfg, type="ban", feature="format", value="memee")
    for feature, value in [
        ("story_type", "gossip"),
        ("tone", "angry"),
        ("persona", "nobody"),
        ("repo", "nope"),
        ("group", "dev"),
        ("dir", "nope"),
        ("dir", "other/billing"),
        ("visual_kind", "hologram"),
        ("recency", "ancient"),
        ("has_comments", "maybe"),
        ("interactive", "meme"),
        ("difficulty", "9"),
    ]:
        with pytest.raises(steering.SteeringError, match=feature):
            steering.add_rule(conn, cfg, type="ban", feature=feature, value=value)
    ok = [
        ("story_type", "rip"),
        ("format", "meme"),
        ("tone", "roast"),
        ("persona", "greybeard"),
        ("repo", "fixture"),
        ("visual_kind", "code"),
        ("template", "hot_take"),
        ("recency", "new"),
        ("difficulty", "2"),
        ("interactive", "quiz"),
    ]
    for feature, value in ok:
        assert (
            steering.add_rule(conn, cfg, type="ban", feature=feature, value=value)["value"] == value
        )


def test_add_rule_dir_accepts_repo_prefix_and_checks_the_ref(conn, cfg):
    plain = steering.add_rule(conn, cfg, type="boost", feature="dir", value="billing")
    prefixed = steering.add_rule(conn, cfg, type="boost", feature="dir", value="fixture/billing/")
    assert plain["value"] == prefixed["value"] == "billing"


def test_add_rule_group_and_has_comments_values(conn, cfg):
    from dataclasses import replace

    from codescroll.config import Group

    cfg = replace(cfg, groups={"dev": Group("dev", ("fixture",))})
    assert steering.add_rule(conn, cfg, type="ban", feature="group", value="dev")
    r = steering.add_rule(conn, cfg, type="ban", feature="has_comments", value="yes")
    assert r["value"] == "1"


def test_add_rule_expiry_forms(conn, cfg):
    def add(expires):
        return steering.add_rule(
            conn, cfg, type="ban", feature="format", value="meme", expires=expires, now=NOW
        )["expires_at"]

    assert add("7d") == "2026-06-08T12:00:00Z"
    assert add("2w") == "2026-06-15T12:00:00Z"
    assert add("12h") == "2026-06-02T00:00:00Z"
    assert add("2026-11-06") == "2026-11-06T23:59:59Z"
    assert add("2026-11-06T10:30:00Z") == "2026-11-06T10:30:00Z"
    assert add("2026-11-06T10:30:00+02:00") == "2026-11-06T08:30:00Z"
    assert add(None) is None
    for bad in ("soon", "0d", "-3d", "2020-01-01", "7x"):
        with pytest.raises(steering.SteeringError, match="expires"):
            add(bad)


def test_add_rule_keeps_creator_and_reason(conn, cfg):
    r = steering.add_rule(
        conn, cfg, type="ban", feature="format", value="meme",
        created_by="user", reason="less memes please",
    )  # fmt: skip
    assert (r["created_by"], r["reason"]) == ("user", "less memes please")


def test_list_rules_hides_expired_unless_asked(conn, cfg):
    keep = steering.add_rule(conn, cfg, type="ban", feature="format", value="meme")
    soon = steering.add_rule(
        conn, cfg, type="ban", feature="tone", value="roast", expires="7d", now=NOW
    )
    old = steering.add_rule(
        conn, cfg, type="ban", feature="tone", value="hype", expires="1d", now=NOW
    )
    later = NOW + timedelta(days=3)
    assert [r["id"] for r in steering.list_rules(conn, now=later)] == [keep["id"], soon["id"]]
    everything = steering.list_rules(conn, include_expired=True, now=later)
    assert [(r["id"], r["expired"]) for r in everything] == [
        (keep["id"], False),
        (soon["id"], False),
        (old["id"], True),
    ]
    json.dumps(everything)


def test_remove_rule_deletes_and_rejects_unknown(conn, cfg):
    rule = steering.add_rule(conn, cfg, type="ban", feature="format", value="meme")
    out = steering.remove_rule(conn, rule["id"])
    assert out["removed"] is True and out["rule"]["id"] == rule["id"]
    assert steering.list_rules(conn) == []
    with pytest.raises(steering.SteeringError, match="No rule with id"):
        steering.remove_rule(conn, rule["id"])


# ---------------------------------------------------------------- weights and profile helpers


def add_card(conn, cfg, created_at="2026-05-31T00:00:00Z", **over) -> str:
    if not conn.execute("SELECT 1 FROM runs WHERE id = 'r1'").fetchone():
        conn.execute(
            "INSERT INTO runs(id, status, started_at) "
            "VALUES ('r1', 'finished', '2026-05-30T00:00:00Z')"
        )
    spec = text_card(SimpleNamespace(shas={"delete_legacy": "abc"}), **over)
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, "r1", acc, now=created_at)
    conn.commit()
    return cid


def reward(conn, cfg, card_id, value, days_ago, now=NOW):
    """One impression with a reward, and the weight update the learner would make."""
    ts = int((now - timedelta(days=days_ago)).timestamp() * 1000)
    cur = conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', 'x')",
        (card_id, ts),
    )
    conn.execute(
        "INSERT INTO rewards(card_id, impression_event_id, reward, computed_at) "
        "VALUES (?, ?, ?, ?)",
        (card_id, cur.lastrowid, value, "2026-06-01T00:00:00Z"),
    )
    rc = learning.load_reward_config(cfg)
    for f, v in learning.card_features(conn, cfg, card_id, now=now):
        learning._update_weight(conn, cfg, rc, f, v, value, now)
    conn.commit()


@pytest.fixture
def taste(conn, cfg):
    """meme: 5 good a while ago, 5 weak lately. chart: weak then good. text_post: lately only."""
    meme = add_card(conn, cfg, format="meme")
    chart = add_card(conn, cfg, format="chart")
    post = add_card(conn, cfg, format="text_post")
    for _ in range(5):
        reward(conn, cfg, meme, 0.9, 15)
        reward(conn, cfg, meme, 0.3, 2)
    for _ in range(3):
        reward(conn, cfg, chart, 0.2, 15)
        reward(conn, cfg, chart, 0.8, 2)
    for _ in range(4):
        reward(conn, cfg, post, 0.6, 1)
    return {"meme": meme, "chart": chart, "post": post}


def test_explain_weights_reports_evidence_hit_rate_and_trend(conn, cfg, taste):
    rows = steering.explain_weights(conn, cfg, feature="format", now=NOW)
    by_value = {r["value"]: r for r in rows}
    assert set(by_value) == {"meme", "chart", "text_post"}
    meme = by_value["meme"]
    assert meme["feature"] == "format"
    assert meme["impressions"] == 10
    assert meme["hit_rate"] == 0.5
    assert meme["trend"] == "down"
    assert meme["n"] == pytest.approx(10, abs=0.5)
    assert 0 < meme["mean"] < 1
    assert by_value["chart"]["trend"] == "up"
    assert by_value["text_post"]["trend"] == "flat"
    assert by_value["text_post"]["hit_rate"] == 1.0
    assert [r["mean"] for r in rows] == sorted((r["mean"] for r in rows), reverse=True)
    json.dumps(rows)


def test_explain_weights_all_features_sorted_and_rejects_unknown(conn, cfg, taste):
    rows = steering.explain_weights(conn, cfg, now=NOW)
    features = [r["feature"] for r in rows]
    assert features == sorted(features)
    assert {"format", "tone", "repo", "recency"} <= set(features)
    with pytest.raises(steering.SteeringError, match="feature"):
        steering.explain_weights(conn, cfg, feature="colour")


def test_get_profile_writes_plain_claims_from_evidence(conn, cfg, taste):
    steering.add_rule(conn, cfg, type="ban", feature="format", value="horoscope", now=NOW)
    p = steering.get_profile(conn, cfg, now=NOW)
    assert p["evidence"] == 20
    assert (
        "You read meme cards to the end 50% of the time over 10 views, trending down."
        in (p["summary"])
    )
    assert (
        "You read chart cards to the end 50% of the time over 6 views, trending up."
        in (p["summary"])
    )
    assert not any("text_post" in line for line in p["summary"])  # only 4 views: no claim
    ranked = [r["value"] for r in steering.explain_weights(conn, cfg, "format", now=NOW)]
    ranked = [v for v in ranked if v in ("meme", "chart")]  # the two with n >= 5
    assert (p["top"]["format"]["value"], p["bottom"]["format"]["value"]) == (ranked[0], ranked[1])
    assert "tone" not in p["top"]  # one value only: nothing to compare
    assert [r["value"] for r in p["rules"]] == ["horoscope"]
    json.dumps(p)


def test_get_profile_says_when_data_is_thin(conn, cfg):
    assert steering.get_profile(conn, cfg, now=NOW) == {
        "summary": ["Not enough data yet: 0 views so far. Keep scrolling and check back."],
        "top": {},
        "bottom": {},
        "rules": [],
        "evidence": 0,
    }


# ---------------------------------------------------------------- coverage and cards


def impress(conn, card_id, ts_ms, type_="impression", data="{}"):
    conn.execute(
        "INSERT INTO events(card_id, type, ts, data, received_at) VALUES (?, ?, ?, ?, 'x')",
        (card_id, type_, ts_ms, data),
    )
    conn.commit()


def test_coverage_lists_top_level_dirs_least_seen_first(conn, cfg):
    billing = add_card(conn, cfg, dirs=["billing/sub"])
    add_card(conn, cfg, dirs=["src"])
    t = int(NOW.timestamp() * 1000)
    for i in range(3):
        impress(conn, billing, t + i)
    rows = steering.coverage(conn, cfg)
    assert [(r["repo"], r["dir"]) for r in rows] == [
        ("fixture", "data"),
        ("fixture", "src"),
        ("fixture", "billing"),
    ]
    by_dir = {r["dir"]: r for r in rows}
    assert (by_dir["billing"]["impressions"], by_dir["billing"]["cards"]) == (3, 1)
    assert by_dir["billing"]["last_seen"] == "2026-06-01T12:00:00Z"
    assert (by_dir["src"]["impressions"], by_dir["src"]["cards"]) == (0, 1)
    assert by_dir["src"]["last_seen"] is None
    assert by_dir["data"]["cards"] == 0
    assert steering.coverage(conn, cfg, repo="fixture") == rows
    json.dumps(rows)


def test_coverage_uses_churn_signal_dirs_and_rejects_unknown_repo(conn, cfg):
    from codescroll import signals

    signals.analyze(conn, cfg.repos["fixture"], cfg.settings.analysis)
    dirs = {r["dir"] for r in steering.coverage(conn, cfg)}
    assert {"billing", "src", "data"} <= dirs
    assert not any("/" in d or d == "." for d in dirs)
    with pytest.raises(steering.SteeringError, match="Unknown repo"):
        steering.coverage(conn, cfg, repo="nope")


def test_recent_cards_newest_first_with_engagement(conn, cfg):
    old = add_card(conn, cfg, created_at="2026-05-01T00:00:00Z", hook="Old hook.")
    new = add_card(conn, cfg, created_at="2026-05-30T00:00:00Z", hook="New hook.")
    reward(conn, cfg, new, 0.25, 1)
    reward(conn, cfg, new, 0.75, 1)
    rows = steering.recent_cards(conn)
    assert [r["id"] for r in rows] == [new, old]
    assert rows[0] == {
        "id": new,
        "created_at": "2026-05-30T00:00:00Z",
        "story_type": "rip",
        "format": "text_post",
        "hook": "New hook.",
        "status": "ready",
        "impressions": 2,
        "mean_reward": 0.5,
    }
    assert (rows[1]["impressions"], rows[1]["mean_reward"]) == (0, None)
    assert [r["id"] for r in steering.recent_cards(conn, limit=1)] == [new]


def test_card_stats_sums_events_dwell_rewards_answers(conn, cfg):
    cid = add_card(conn, cfg)
    t = int(NOW.timestamp() * 1000)
    impress(conn, cid, t)
    impress(conn, cid, t + 10)
    impress(conn, cid, t + 20, "dwell", '{"ms": 1000}')
    impress(conn, cid, t + 30, "dwell", '{"ms": 3000}')
    impress(conn, cid, t + 40, "answer", '{"choice": 1, "correct": true}')
    reward(conn, cfg, cid, 0.4, 1)
    reward(conn, cfg, cid, 0.6, 1)
    stats = steering.card_stats(conn, cid)
    assert stats["card_id"] == cid
    assert stats["events"] == {"answer": 1, "dwell": 2, "impression": 4}
    assert stats["dwell_ms"] == {"total": 4000, "mean": 2000.0}
    assert stats["rewards"] == [0.4, 0.6] and stats["mean_reward"] == 0.5
    assert stats["answers"] == [{"choice": 1, "correct": True, "ts": t + 40}]
    json.dumps(stats)
    with pytest.raises(steering.SteeringError, match="No card"):
        steering.card_stats(conn, "nope")


def test_reset_defaults_wraps_learning_reset(conn, cfg, taste):
    n_format = conn.execute("SELECT COUNT(*) FROM weights WHERE feature = 'format'").fetchone()[0]
    assert steering.reset_defaults(conn, "format") == {"deleted": n_format}
    assert conn.execute("SELECT COUNT(*) FROM weights WHERE feature = 'format'").fetchone()[0] == 0
    left = conn.execute("SELECT COUNT(*) FROM weights").fetchone()[0]
    assert left > 0
    assert steering.reset_defaults(conn) == {"deleted": left}
    with pytest.raises(steering.SteeringError, match="feature"):
        steering.reset_defaults(conn, "colour")


# ---------------------------------------------------------------- config edits


REPOS_YAML = """\
# Repos header comment
groups:
  dev:
    repos: [alpha]   # dev repos
  # keep this note
  ops:
    repos: [beta]

repos:
  alpha:
    path: {path}
    mascot: crow   # trailing note
  beta:
    path: {path}
    ref: main
# tail comment
"""
MASCOTS_YAML = """\
# mascots header
mascots:
  crow:
    repo: alpha
    style: "a crow"   # keep
    seed: 7
"""
PERSONAS_YAML = """\
# personas header
personas:
  greybeard:
    name: Greybeard
    voice: Grumpy senior engineer.   # keep
  penny:
    name: Penny
    voice: Enthusiastic junior.
"""


def make_ycfg(fixture_repo, tmp_path):
    """A config loaded from real yaml files (with comments) under tmp_path/config."""
    d = tmp_path / "ycfg" / "config"
    d.mkdir(parents=True)
    (d / "repos.yaml").write_text(REPOS_YAML.format(path=fixture_repo.path))
    (d / "mascots.yaml").write_text(MASCOTS_YAML)
    (d / "personas.yaml").write_text(PERSONAS_YAML)
    return config_mod.load_config(tmp_path / "ycfg")


@pytest.fixture
def ycfg(fixture_repo, tmp_path):
    return make_ycfg(fixture_repo, tmp_path)


def text(cfg, name):
    return (cfg.root / "config" / name).read_text()


def comments(s):
    return [ln[ln.index("#") :] for ln in s.splitlines() if "#" in ln]


def test_set_group_moves_repo_and_keeps_comments(ycfg):
    before = comments(text(ycfg, "repos.yaml"))
    assert steering.set_group(ycfg, "alpha", "ops") == {"repo": "alpha", "group": "ops"}
    new = config_mod.load_config(ycfg.root)
    assert new.repos["alpha"].group == "ops"
    assert new.groups["dev"].repos == ()
    assert set(new.groups["ops"].repos) == {"alpha", "beta"}
    assert comments(text(ycfg, "repos.yaml")) == before
    assert "mascot: crow" in text(ycfg, "repos.yaml")


def test_set_group_creates_group_and_can_clear_it(ycfg):
    steering.set_group(ycfg, "beta", "newbies")
    assert config_mod.load_config(ycfg.root).repos["beta"].group == "newbies"
    steering.set_group(ycfg, "beta", None)
    new = config_mod.load_config(ycfg.root)
    assert new.repos["beta"].group is None
    assert "beta" not in new.groups["ops"].repos
    with pytest.raises(steering.SteeringError, match="Unknown repo"):
        steering.set_group(ycfg, "nope", "ops")
    with pytest.raises(steering.SteeringError, match="group name"):
        steering.set_group(ycfg, "beta", "bad name!")


def test_config_edit_is_undone_when_reload_fails(ycfg, monkeypatch):
    before = text(ycfg, "repos.yaml")

    def boom(root):
        raise config_mod.ConfigError("nope")

    monkeypatch.setattr(steering, "load_config", boom)
    with pytest.raises(steering.SteeringError, match="undone"):
        steering.set_group(ycfg, "alpha", "ops")
    assert text(ycfg, "repos.yaml") == before


def test_add_repo_appends_entry_checks_git_and_keeps_comments(ycfg, fixture_repo, tmp_path):
    before = comments(text(ycfg, "repos.yaml"))
    out = steering.add_repo(
        ycfg, "gamma", str(fixture_repo.path), ref="main", group="ops", mascot="crow"
    )
    assert out == {
        "name": "gamma",
        "path": str(fixture_repo.path.resolve()),
        "ref": "main",
        "group": "ops",
        "mascot": "crow",
    }
    new = config_mod.load_config(ycfg.root)
    g = new.repos["gamma"]
    assert (g.ref, g.group, g.mascot) == ("main", "ops", "crow")
    assert "gamma" in new.groups["ops"].repos
    assert comments(text(ycfg, "repos.yaml")) == before
    assert list(new.repos) == ["alpha", "beta", "gamma"]

    plain = tmp_path / "plain"
    plain.mkdir()
    for args, word in [
        (("delta", str(plain)), "git repo"),
        (("alpha", str(fixture_repo.path)), "already"),
        (("bad name", str(fixture_repo.path)), "repo name"),
        (("delta", str(fixture_repo.path)), None),
    ]:
        if word is None:
            steering.add_repo(ycfg, *args)  # defaults: ref stays unset, no group
            assert config_mod.load_config(ycfg.root).repos["delta"].ref == "HEAD"
            continue
        with pytest.raises(steering.SteeringError, match=word):
            steering.add_repo(ycfg, *args)
    with pytest.raises(steering.SteeringError, match="ref"):
        steering.add_repo(ycfg, "eps", str(fixture_repo.path), ref="no-such-branch")
    with pytest.raises(steering.SteeringError, match="mascot"):
        steering.add_repo(ycfg, "eps", str(fixture_repo.path), mascot="ghost")
    assert "eps" not in config_mod.load_config(ycfg.root).repos


def test_set_mascot_updates_fields_and_links_repo(ycfg):
    out = steering.set_mascot(ycfg, "crow", style="a very large crow", seed=99)
    assert out == {"name": "crow", "repo": "alpha", "style": "a very large crow", "seed": 99}
    m = config_mod.load_config(ycfg.root).mascots["crow"]
    assert (m.repo, m.style, m.seed) == ("alpha", "a very large crow", 99)
    assert "# keep" in text(ycfg, "mascots.yaml") and "# mascots header" in text(
        ycfg, "mascots.yaml"
    )

    steering.set_mascot(ycfg, "otter", repo="beta", style="an otter")
    new = config_mod.load_config(ycfg.root)
    assert new.mascots["otter"].repo == "beta" and new.mascots["otter"].seed > 0
    assert new.repos["beta"].mascot == "otter"
    assert "crow" in new.mascots and new.repos["alpha"].mascot == "crow"
    assert "# trailing note" in text(ycfg, "repos.yaml")

    with pytest.raises(steering.SteeringError, match="style"):
        steering.set_mascot(ycfg, "fresh")
    with pytest.raises(steering.SteeringError, match="Unknown repo"):
        steering.set_mascot(ycfg, "crow", repo="nope")


def test_edit_persona_changes_only_given_fields(ycfg):
    out = steering.edit_persona(ycfg, "greybeard", voice="Tired: has seen #everything.")
    assert out == {
        "handle": "greybeard",
        "name": "Greybeard",
        "voice": "Tired: has seen #everything.",
    }
    new = config_mod.load_config(ycfg.root)
    assert new.personas["greybeard"].voice == "Tired: has seen #everything."
    assert new.personas["greybeard"].name == "Greybeard"
    assert new.personas["penny"].voice == "Enthusiastic junior."
    assert "# keep" in text(ycfg, "personas.yaml")

    steering.edit_persona(ycfg, "newbie", name="Newbie", voice="Curious.")
    assert config_mod.load_config(ycfg.root).personas["newbie"].name == "Newbie"
    with pytest.raises(steering.SteeringError, match="name and voice"):
        steering.edit_persona(ycfg, "other", name="Other")
    with pytest.raises(steering.SteeringError, match="Nothing to change"):
        steering.edit_persona(ycfg, "greybeard")
