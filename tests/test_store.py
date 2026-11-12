import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from blamescroll import db, store, validator
from blamescroll.config import (
    AgentSettings,
    AnalysisSettings,
    Config,
    Repo,
    ResearchSettings,
    ServerSettings,
    Settings,
)
from tests.cards import example_card, explain, guess_who_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    repo = Repo(name="fixture", path=fixture_repo.path, ref="main")
    settings = Settings(
        data_dir=tmp_path / "data",
        server=ServerSettings(),
        agent=AgentSettings(),
        analysis=AnalysisSettings(),
        research=ResearchSettings(),
    )
    return Config(
        root=tmp_path,
        repos={"fixture": repo},
        groups={},
        settings=settings,
        defaults={},
        personas={},
    )


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


def _insert_run(conn, run_id="r_1"):
    conn.execute(
        "INSERT INTO runs(id, status, started_at) VALUES (?, 'open', ?)",
        (run_id, db.now_iso()),
    )
    conn.commit()


def _accept(cfg, card):
    # These tests are about storage, not about which format suits a story type.
    pair = {(card["story_type"], card["format"])}
    accepted, rejected = validator.validate_cards([card], cfg.repos, PERSONAS, variant_formats=pair)
    assert rejected == []
    return accepted[0]


def test_store_card_writes_features(conn, cfg, fixture_repo):
    _insert_run(conn)
    acc = _accept(cfg, example_card(fixture_repo))
    card_id = store.store_card(conn, cfg, "r_1", acc, now="2026-02-01T00:00:00Z")

    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    assert row["run_id"] == "r_1"
    assert row["status"] == "ready"
    assert row["story_key"] == acc.story_key
    assert row["created_at"] == "2026-02-01T00:00:00Z"
    assert db.loads(row["spec"]) == acc.card
    assert db.loads(row["resolved"]) == acc.resolved
    repo_name = conn.execute("SELECT name FROM repos WHERE id = ?", (row["repo_id"],)).fetchone()[0]
    assert repo_name == "fixture"

    feats = {
        (r["feature"], r["value"])
        for r in conn.execute("SELECT * FROM card_features WHERE card_id = ?", (card_id,))
    }
    assert feats == {
        ("story_type", "what_it_does"),
        ("format", "code_card"),
        ("persona", "paranoid_sec"),
        ("tone", "dry-deadpan"),
        ("repo", "fixture"),
        ("dir", "billing"),
        ("difficulty", "2"),
        ("has_comments", "1"),
        ("visual_kind", "code"),
    }


def test_interactive_card_gets_interactive_feature_with_story_type(
    conn, cfg, fixture_repo, monkeypatch
):
    monkeypatch.setattr(store, "SHUFFLE", True)  # the real store path shuffles
    _insert_run(conn)
    acc = _accept(cfg, guess_who_card(fixture_repo))
    card_id = store.store_card(conn, cfg, "r_1", acc)
    feats = {
        (r["feature"], r["value"])
        for r in conn.execute("SELECT * FROM card_features WHERE card_id = ?", (card_id,))
    }
    assert ("interactive", "guess_who") in feats
    assert ("story_type", "guess_who") in feats
    row = conn.execute("SELECT spec, resolved FROM cards WHERE id = ?", (card_id,)).fetchone()
    spec, resolved = db.loads(row["spec"]), db.loads(row["resolved"])
    right = acc.card["interaction"]["choices"][0]  # the fixture's answer is first
    assert spec["interaction"]["choices"][spec["interaction"]["answer_index"]] == right
    assert resolved["interaction"] == {"answer_index": spec["interaction"]["answer_index"]}


def test_stored_quiz_choices_are_shuffled_so_the_answer_is_not_always_first():
    """Live: writers put the answer at index 0 or 1 on every spot_the_bug card."""
    card = {"interaction": {"question": "q", "choices": ["a", "b", "c", "d"], "answer_index": 0}}
    resolved = {"interaction": {"answer_index": 0}}
    positions = set()
    for n in range(40):
        c, r = store.shuffle_choices(card, resolved, f"c_{n}")
        inter = c["interaction"]
        assert inter["choices"][inter["answer_index"]] == "a"
        assert sorted(inter["choices"]) == ["a", "b", "c", "d"]
        assert r["interaction"]["answer_index"] == inter["answer_index"]
        positions.add(inter["answer_index"])
    assert positions == {0, 1, 2, 3}
    assert card["interaction"]["choices"] == ["a", "b", "c", "d"]  # input untouched
    tot = {"interaction": {"question": "q", "choices": ["x", "y"]}}  # this_or_that: no answer
    assert store.shuffle_choices(tot, {}, "c_1") == (tot, {})


def test_plain_card_has_no_interactive_feature(conn, cfg, fixture_repo):
    _insert_run(conn)
    card_id = store.store_card(conn, cfg, "r_1", _accept(cfg, example_card(fixture_repo)))
    assert not conn.execute(
        "SELECT 1 FROM card_features WHERE card_id = ? AND feature = 'interactive'", (card_id,)
    ).fetchone()


def test_insert_card_upserts_story(conn, cfg, fixture_repo):
    _insert_run(conn)
    acc = _accept(cfg, example_card(fixture_repo))
    store.store_card(conn, cfg, "r_1", acc, now="2026-02-01T00:00:00Z")

    row = conn.execute("SELECT * FROM stories WHERE story_key = ?", (acc.story_key,)).fetchone()
    assert row["repo"] == "fixture" and row["story_type"] == acc.card["story_type"]
    assert db.loads(row["sources"]) == acc.card["sources"]
    assert (row["first_card_at"], row["last_card_at"]) == ("2026-02-01T00:00:00Z",) * 2
    assert (row["cards_made"], row["best_reward"], row["liked"]) == (1, None, 0)

    conn.execute("DELETE FROM cards")  # the unique index on cards.story_key would block a repeat
    store.store_card(conn, cfg, "r_1", acc, now="2026-02-05T00:00:00Z")
    row = conn.execute("SELECT * FROM stories WHERE story_key = ?", (acc.story_key,)).fetchone()
    assert row["cards_made"] == 2
    assert (row["first_card_at"], row["last_card_at"]) == (
        "2026-02-01T00:00:00Z",
        "2026-02-05T00:00:00Z",
    )


def test_ensure_repo_upserts_by_name(conn, tmp_path):
    first = store.ensure_repo(conn, Repo(name="a", path=tmp_path, ref="main"))
    again = store.ensure_repo(conn, Repo(name="a", path=tmp_path / "x", ref="dev", mascot="owl"))
    assert first == again
    row = conn.execute("SELECT * FROM repos WHERE id = ?", (first,)).fetchone()
    assert (row["path"], row["ref"], row["mascot"]) == (str(tmp_path / "x"), "dev", "owl")


def test_card_ids_sort_by_time():
    ids = [store.new_card_id(ms) for ms in (1_000, 2_000, 1_700_000_000_000)]
    assert ids == sorted(ids)
    assert all(i.startswith("c_") and len(i) == 2 + 12 + 8 for i in ids)
    assert store.new_card_id(5) != store.new_card_id(5)


def _store_kind(conn, cfg, card):
    from blamescroll.config import Mascot, MemeTemplate

    accepted, rejected = validator.validate_cards(
        [card],
        cfg.repos,
        PERSONAS,
        meme_templates={"drake": MemeTemplate("drake", 2)},
        mascots={"otter": Mascot("otter", "fixture", "s", 1)},
    )
    assert rejected == []
    _insert_run(conn)
    cid = store.store_card(conn, cfg, "r_1", accepted[0])
    status = conn.execute("SELECT status FROM cards WHERE id = ?", (cid,)).fetchone()[0]
    feats = {
        (r["feature"], r["value"])
        for r in conn.execute("SELECT * FROM card_features WHERE card_id = ?", (cid,))
    }
    return status, feats


def test_render_kinds_are_pending_render(conn, cfg, fixture_repo):
    from tests import cards as C

    status, feats = _store_kind(conn, cfg, C.meme_card(fixture_repo))
    assert status == "pending_render"
    assert ("visual_kind", "meme") in feats
    assert ("meme_template", "drake") in feats


@pytest.mark.parametrize("make", ["illustration_card", "comic_card"])
def test_image_kinds_are_pending_render(conn, cfg, fixture_repo, make):
    from tests import cards as C

    assert _store_kind(conn, cfg, getattr(C, make)(fixture_repo))[0] == "pending_render"


@pytest.mark.parametrize("make", ["text_meme_card", "diagram_card"])
def test_client_rendered_kinds_are_ready(conn, cfg, fixture_repo, make):
    from tests import cards as C

    status, feats = _store_kind(conn, cfg, getattr(C, make)(fixture_repo))
    assert status == "ready"
    assert not any(f == "template" for f, _ in feats)


def test_template_feature_row(conn, cfg, fixture_repo):
    from tests import cards as C

    status, feats = _store_kind(conn, cfg, C.template_card(fixture_repo, "hot_take"))
    assert status == "ready"
    assert ("visual_kind", "template") in feats
    assert ("template", "hot_take") in feats


def _dirs(card):
    return {v for f, v in store._features(card) if f == "dir"}


def test_dir_features_include_all_prefixes_and_source_dirs(fixture_repo):
    card = example_card(fixture_repo, dirs=["src/app/"])
    card["visual"]["path"] = "lib/core/x.py"
    card["depth"] = [
        {"kind": "code", "repo": "fixture", "path": "docs/guide/a.md"},
        {"kind": "code_diff", "repo": "fixture", "commit": "abc", "path": "tools/b.py"},
        {"kind": "explain", "text": "no path"},
    ]
    card["sources"] = [{"repo": "fixture", "path": "billing/deep/er/f.py"}, {"commit": "abc"}]
    assert _dirs(card) == {
        "src",
        "src/app",
        "lib",
        "lib/core",
        "docs",
        "docs/guide",
        "tools",
        "billing",
        "billing/deep",
        "billing/deep/er",
    }


def test_root_file_adds_no_dir(fixture_repo):
    card = example_card(fixture_repo, dirs=[])
    card["visual"]["path"] = "README.md"
    card["depth"] = []
    card["sources"] = [{"repo": "fixture", "path": "setup.py"}]
    assert _dirs(card) == set()


VARIANT_NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _story_row(conn, key, **over):
    sets = ", ".join(f"{k} = ?" for k in over)
    conn.execute(f"UPDATE stories SET {sets} WHERE story_key = ?", (*over.values(), key))
    conn.commit()
    return conn.execute("SELECT * FROM stories WHERE story_key = ?", (key,)).fetchone()


def _variant_story(conn, cfg, fixture_repo, **over):
    """A story told once as text_post 20 days ago, with a good reward unless overridden."""
    _insert_run(conn)
    acc = _accept(cfg, text_card(fixture_repo))
    created = (VARIANT_NOW - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.store_card(conn, cfg, "r_1", acc, now=created)
    row = _story_row(conn, acc.story_key, **{"best_reward": 0.8, **over})
    return acc, row


def _decide(cfg, row, fmt, now=VARIANT_NOW):
    return store.variant_blocker(row, fmt, cfg.settings.agent, now)


def test_variant_card_allowed_with_different_format(conn, cfg, fixture_repo):
    acc, row = _variant_story(conn, cfg, fixture_repo)
    assert db.loads(row["formats"]) == ["text_post"]
    assert _decide(cfg, None, "meme") is None  # a new story is always fine
    assert _decide(cfg, row, "meme") is None
    # The unique index is (story_key, format): a second format inserts.
    other = _accept(cfg, text_card(fixture_repo, format="fun_fact"))
    assert other.story_key == acc.story_key
    store.store_card(conn, cfg, "r_1", other, now="2026-03-01T00:00:00Z")
    row = conn.execute("SELECT * FROM stories WHERE story_key = ?", (acc.story_key,)).fetchone()
    assert db.loads(row["formats"]) == ["text_post", "fun_fact"]
    assert row["cards_made"] == 2
    with pytest.raises(sqlite3.IntegrityError):  # same story and format twice still fails
        store.store_card(conn, cfg, "r_1", other, now="2026-03-02T00:00:00Z")


def test_variant_rejected_same_format(conn, cfg, fixture_repo):
    _, row = _variant_story(conn, cfg, fixture_repo)
    assert "format" in _decide(cfg, row, "text_post")


def test_variant_rejected_too_soon(conn, cfg, fixture_repo):
    _, row = _variant_story(conn, cfg, fixture_repo)
    soon = VARIANT_NOW - timedelta(days=10)  # the last card is then 10 days old
    assert "14 days" in _decide(cfg, row, "meme", now=soon)


def test_variant_rejected_low_reward_unless_liked(conn, cfg, fixture_repo):
    acc, row = _variant_story(conn, cfg, fixture_repo, best_reward=0.3)
    assert "reward" in _decide(cfg, row, "meme")
    row = _story_row(conn, acc.story_key, best_reward=None)
    assert "reward" in _decide(cfg, row, "meme")
    row = _story_row(conn, acc.story_key, liked=1)
    assert _decide(cfg, row, "meme") is None


def test_predicted_story_key_matches_the_validators(cfg, fixture_repo):
    from blamescroll import storykey

    card = text_card(fixture_repo)
    sha = card["sources"][0]["commit"]
    assert storykey.story_key("rip", "fixture", commit=sha) == _accept(cfg, card).story_key
    card["sources"] = [{"repo": "fixture", "path": "billing/invoice.py", "lines": [1, 3]}]
    card["depth"][0]["text"] = explain("billing/invoice.py")
    assert (
        storykey.story_key("rip", "fixture", path="billing/invoice.py", lines=(1, 3))
        == _accept(cfg, card).story_key
    )
    card["sources"] = [{"repo": "fixture", "path": "billing/invoice.py"}]
    assert (
        storykey.story_key("rip", "fixture", path="billing/invoice.py")
        == _accept(cfg, card).story_key
    )


def test_verdict_becomes_a_feature(conn, cfg, fixture_repo):
    _insert_run(conn)
    card = example_card(fixture_repo, verdict="cursed")
    card["comments"] = [
        {"persona": "greybeard", "text": "Legacy float math that callers still depend on, sadly."}
    ]
    card_id = store.store_card(conn, cfg, "r_1", _accept(cfg, card))
    feats = {
        (r["feature"], r["value"])
        for r in conn.execute("SELECT * FROM card_features WHERE card_id = ?", (card_id,))
    }
    assert ("verdict", "cursed") in feats
