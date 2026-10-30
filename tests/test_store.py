from datetime import UTC, datetime, timedelta

import pytest

from codescroll import db, store, validator
from codescroll.config import (
    AgentSettings,
    AnalysisSettings,
    Config,
    Repo,
    ResearchSettings,
    ServerSettings,
    Settings,
)
from tests.cards import example_card

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
    accepted, rejected = validator.validate_cards([card], cfg.repos, PERSONAS)
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
        ("story_type", "commit_drama"),
        ("format", "code_card"),
        ("persona", "paranoid_sec"),
        ("tone", "dry-deadpan"),
        ("repo", "fixture"),
        ("dir", "billing"),
        ("difficulty", "2"),
        ("has_comments", "1"),
        ("visual_kind", "code"),
    }


def test_story_key_exists_respects_window(conn, cfg, fixture_repo):
    _insert_run(conn)
    acc = _accept(cfg, example_card(fixture_repo))
    now = datetime(2026, 3, 1, tzinfo=UTC)
    created = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.store_card(conn, cfg, "r_1", acc, now=created)

    assert store.story_key_exists(conn, acc.story_key, now=now)
    assert not store.story_key_exists(conn, "other", now=now)
    assert not store.story_key_exists(conn, acc.story_key, since_days=5, now=now)


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
    from codescroll.config import Mascot, MemeTemplate

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
