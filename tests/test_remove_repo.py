"""Removing a repo removes what GitTok made for it: cards, rows, files, profile, mascot."""

import json
import random
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from gittok import brief, cli, db, feed, gc, learning, steering, store, supply
from gittok import config as config_mod
from tests.cards import text_card
from tests.test_steering import comments, make_ycfg, text

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
PROFILE = "version: 1\nstack: [python]\n"


@pytest.fixture
def ycfg(fixture_repo, tmp_path):
    return make_ycfg(fixture_repo, tmp_path)


def open_db(cfg):
    return db.open_db(cfg.settings.data_dir / "gittok.db")


def add_card(conn, cfg, repos, run="r1", created_at="2026-05-31T00:00:00Z") -> str:
    if not conn.execute("SELECT 1 FROM runs WHERE id = ?", (run,)).fetchone():
        conn.execute(
            "INSERT INTO runs(id, status, started_at) "
            "VALUES (?, 'finished', '2026-05-30T00:00:00Z')",
            (run,),
        )
    spec = text_card(
        SimpleNamespace(shas={"delete_legacy": "abc"}),
        repos=repos,
        sources=[{"repo": r, "commit": "abc"} for r in repos],
    )
    acc = SimpleNamespace(card=spec, resolved={}, story_key=f"k{random.random()}")
    cid = store.insert_card(conn, cfg, run, acc, now=created_at)
    conn.commit()
    return cid


# Every table that can hold a row for one repo or one of its cards, and how to count them.
BY_CARD = (
    "cards:id",
    "card_features:card_id",
    "assets:card_id",
    "events:card_id",
    "rewards:card_id",
    "srs:card_id",
    "notifications:card_id",
    "saved_cards:card_id",
    "knowledge_events:card_id",
    "replies:card_id",
)
BY_NAME = (
    "story_views",
    "stories",
    "candidates",
    "candidate_ratings",
    "scout_batches",
    "leads",
    "knowledge",
    "knowledge_symbols",
    "digests",
)
BY_REPO_ID = (
    "git_signals",
    "repo_groups",
    "mascots",
    "fact_builds",
    "fact_defines",
    "fact_calls",
    "fact_imports",
    "fact_touched",
    "fact_analyzers",
    "fact_schema",
)


def fill(conn, cfg, name: str) -> str:
    """One card of repo `name` and one row in every table that hangs off it or off the repo."""
    cid = add_card(conn, cfg, [name], run=f"run-{name}")
    rid = conn.execute("SELECT id FROM repos WHERE name = ?", (name,)).fetchone()[0]
    conn.execute("UPDATE runs SET repo_id = ?, brief = 'secret' WHERE id = ?", (rid, f"run-{name}"))
    folder = cfg.settings.data_dir / "assets" / cid
    folder.mkdir(parents=True)
    (folder / "a.png").write_bytes(b"x")
    (folder / "b.png").write_bytes(b"x")
    run_dir = cfg.settings.data_dir / "runs" / f"run-{name}"
    run_dir.mkdir(parents=True)
    (run_dir / "brief.md").write_text("x")
    t = "2026-05-31T00:00:00Z"
    q = conn.execute
    q("INSERT INTO assets(card_id, kind, path) VALUES (?, 'image', 'a.png')", (cid,))
    imp = q(
        "INSERT INTO events(card_id, type, ts, data, received_at) "
        "VALUES (?, 'impression', ?, '{}', ?)",
        (cid, int(NOW.timestamp() * 1000) - 3600_000, t),
    ).lastrowid
    q(
        "INSERT INTO rewards(card_id, impression_event_id, reward, computed_at) "
        "VALUES (?, ?, 0.9, ?)",
        (cid, imp, t),
    )
    q("INSERT INTO srs(card_id, interval_days, due_at) VALUES (?, 1, ?)", (cid, t))
    q(
        "INSERT INTO notifications(kind, text, card_id, created_at, dedup_key) "
        "VALUES ('new_kind', 't', ?, ?, ?)",
        (cid, t, f"new_kind:{cid}"),
    )
    q(
        "INSERT INTO notifications(kind, text, created_at, dedup_key) "
        "VALUES ('hot_file', 't', ?, ?)",
        (t, f"hot_file:{name}:2026-05-31"),
    )
    q("INSERT INTO saved_cards(card_id, saved_at, saved_ts) VALUES (?, ?, 1)", (cid, t))
    q(
        "INSERT INTO knowledge_events(event_id, ts, card_id, kind) VALUES (?, 1, ?, 'seen')",
        (imp, cid),
    )
    q(
        "INSERT INTO replies(card_id, persona, comment_index, text, created_at) "
        "VALUES (?, 'penny', 0, 'hi', ?)",
        (cid, t),
    )
    q("INSERT INTO story_views(repo, sha, seen_at) VALUES (?, 'abc', ?)", (name, t))
    q(
        "INSERT INTO candidates(repo, path, line_start, line_end, tag, why, head_sha, "
        "first_seen_at, last_seen_at) VALUES (?, 'a.py', 1, 2, 't', 'w', 'h', ?, ?)",
        (name, t, t),
    )
    q(
        "INSERT INTO candidate_ratings(repo, path, line_start, tag, window_hash, teachable, "
        "verdict, concept, why, rated_at) VALUES (?, 'a.py', 1, 't', 'h', 3, 'good', 'c', 'w', ?)",
        (name, t),
    )
    q(
        "INSERT INTO scout_batches(id, repo, head_sha, items, created_at) "
        "VALUES (?, ?, 'h', '[]', ?)",
        (f"b-{name}", name, t),
    )
    q(
        "INSERT INTO leads(repo, story_type, kind, lead_key, text, strength, head_sha, "
        "first_seen_at, last_seen_at) VALUES (?, 'rip', 'commit', 'k', 't', 1, 'h', ?, ?)",
        (name, t, t),
    )
    q("INSERT INTO knowledge(repo, dir) VALUES (?, 'src')", (name,))
    q("INSERT INTO knowledge_symbols(repo, symbol) VALUES (?, 's')", (name,))
    q("INSERT INTO digests(repo, day, created_at) VALUES (?, '2026-05-31', ?)", (name, t))
    q(
        "INSERT INTO git_signals(repo_id, head_sha, kind, payload, computed_at) "
        "VALUES (?, 'h', 'k', '{}', ?)",
        (rid, t),
    )
    q("INSERT OR IGNORE INTO groups(id, name) VALUES (1, 'g')")
    q("INSERT INTO repo_groups(repo_id, group_id) VALUES (?, 1)", (rid,))
    q("INSERT INTO mascots(name, repo_id) VALUES (?, ?)", (f"m-{name}", rid))
    q(
        "INSERT INTO fact_builds(repo_id, head_sha, built_at, duration_ms, counts, query_key) "
        "VALUES (?, 'h', ?, 1, '{}', 'q')",
        (rid, t),
    )
    q(
        'INSERT INTO fact_defines(fact_id, repo_id, path, symbol, name, kind, start, "end", '
        "size, params, depth, branches, public) "
        "VALUES (?, ?, 'a', 's', 'n', 'f', 1, 2, 1, 0, 0, 0, 1)",
        (f"d-{name}", rid),
    )
    q(
        "INSERT INTO fact_calls(fact_id, repo_id, caller_symbol, callee_name, path, line, "
        "resolved) VALUES (?, ?, 'a', 'b', 'p', 1, 0)",
        (f"c-{name}", rid),
    )
    q(
        "INSERT INTO fact_imports(fact_id, repo_id, path, line, module_text) "
        "VALUES (?, ?, 'p', 1, 'm')",
        (f"i-{name}", rid),
    )
    q(
        "INSERT INTO fact_touched(fact_id, repo_id, commit_sha, ts, symbol, path) "
        "VALUES (?, ?, 'abc', 1, 's', 'p')",
        (f"t-{name}", rid),
    )
    q(
        "INSERT INTO fact_analyzers(repo_id, tool, head_sha, submitted_at, counts) "
        "VALUES (?, 'x', 'h', ?, '{}')",
        (rid, t),
    )
    q(
        "INSERT INTO fact_schema(fact_id, repo_id, kind, path, line, symbol, source) "
        "VALUES (?, ?, 'returns', 'p', 1, 's', 'x')",
        (f"s-{name}", rid),
    )
    q(
        "INSERT INTO rules(type, feature, value, factor, created_at) "
        "VALUES ('boost', 'repo', ?, 2.0, ?)",
        (name, t),
    )
    q(
        "INSERT INTO model_weights(feature, value, mean, precision, n, updated_at) "
        "VALUES ('repo', ?, 0.5, 5, 2, ?)",
        (name, t),
    )
    conn.commit()
    return cid


def rows_of(conn, name: str, cid: str) -> dict[str, int]:
    """Rows per table that belong to repo `name` or its card `cid`."""
    rid = conn.execute("SELECT id FROM repos WHERE name = ?", (name,)).fetchone()
    out = {}
    for spec in BY_CARD:
        table, col = spec.split(":")
        out[spec] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (cid,)
        ).fetchone()[0]
    for table in BY_NAME:
        out[table] = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE repo = ?", (name,)
        ).fetchone()[0]
    for table in BY_REPO_ID:
        out[table] = (
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE repo_id = ?", (rid[0],)).fetchone()[0]
            if rid
            else 0
        )
    out["repos"] = 1 if rid else 0
    out["hot_file"] = conn.execute(
        "SELECT COUNT(*) FROM notifications WHERE dedup_key LIKE ?", (f"hot_file:{name}:%",)
    ).fetchone()[0]
    out["rules"] = conn.execute(
        "SELECT COUNT(*) FROM rules WHERE feature = 'repo' AND value = ?", (name,)
    ).fetchone()[0]
    return out


def test_every_table_with_a_repo_or_card_column_is_decided():
    """A new table that names a repo or a card must get a place in gc.purge_repo (and here)."""
    with closing(db.open_db(":memory:")) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        found = set()
        for t in tables:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info('{t}')")}
            if cols & {"repo", "repo_id", "card_id"}:
                found.add(t)
    known = {s.split(":")[0] for s in BY_CARD} | set(BY_NAME) | set(BY_REPO_ID) | {"runs"}
    assert found - {"cards"} <= known, sorted(found - known)
    assert found - {"cards"} <= gc.REPO_TABLES | gc.CARD_TABLES, sorted(found)


def test_remove_repo_deletes_cards_rows_files_and_profile_and_nothing_of_another_repo(
    ycfg, fixture_repo
):
    data = ycfg.settings.data_dir
    with closing(open_db(ycfg)) as conn:
        a = fill(conn, ycfg, "alpha")
        b = fill(conn, ycfg, "beta")
        learning.process_events(conn, ycfg)  # removal runs the learner first: do it here too
        before_beta = rows_of(conn, "beta", b)
        assert all(n >= 1 for n in rows_of(conn, "alpha", a).values())
    profiles = ycfg.root / "local" / "profiles"
    profiles.mkdir()
    (profiles / "alpha.yaml").write_text(PROFILE)
    (profiles / "beta.yaml").write_text(PROFILE)
    cfg = config_mod.load_config(ycfg.root)

    out = steering.remove_repo(cfg, "alpha")

    assert out["name"] == "alpha" and out["deleted_clone"] is False
    assert out["cards_removed"] == 1 and out["files_removed"] == 3  # 2 images, 1 run file
    assert out["profile_removed"] is True and out["rules_removed"] == 1
    assert out["kept_data"] is False
    assert fixture_repo.path.exists()  # the directory the user gave
    with closing(open_db(ycfg)) as conn:
        assert set(rows_of(conn, "alpha", a).values()) == {0}
        assert rows_of(conn, "beta", b) == before_beta
        # the run row stays (the daily run cap counts it) but holds nothing of the repo
        run = conn.execute("SELECT repo_id, brief FROM runs WHERE id = 'run-alpha'").fetchone()
        assert run["repo_id"] is None and run["brief"] is None
        # learned taste is about the user: the weights stay
        assert (
            conn.execute("SELECT COUNT(*) FROM model_weights WHERE feature = 'repo'").fetchone()[0]
            == 2
        )
    assert not (data / "assets" / a).exists() and (data / "assets" / b).is_dir()
    assert not (data / "runs" / "run-alpha").exists() and (data / "runs" / "run-beta").is_dir()
    assert not (profiles / "alpha.yaml").exists() and (profiles / "beta.yaml").exists()
    assert list(config_mod.load_config(ycfg.root).repos) == ["beta"]
    log = (data / "config_audit.log").read_text()
    assert '"cards_removed": 1' in log


def test_remove_repo_feeds_closed_impressions_to_the_weights_before_it_deletes_them(ycfg):
    with closing(open_db(ycfg)) as conn:
        a = add_card(conn, ycfg, ["alpha"])
        conn.execute(  # an old impression that the learner did not process yet
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', 1000, '{}', 'x')",
            (a,),
        )
        conn.commit()
    steering.remove_repo(ycfg, "alpha")
    with closing(open_db(ycfg)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        learned = {r[0] for r in conn.execute("SELECT feature FROM model_weights")}
    assert {"format", "story_type", "persona"} <= learned


def test_keep_data_removes_only_the_entry_and_gc_and_the_feed_respect_it(ycfg):
    with closing(open_db(ycfg)) as conn:
        a = fill(conn, ycfg, "alpha")
        before = rows_of(conn, "alpha", a)
    profile = ycfg.root / "local" / "profiles" / "alpha.yaml"
    profile.parent.mkdir()
    profile.write_text(PROFILE)
    mascots = (
        text(ycfg, "mascots.yaml") if (ycfg.root / "local" / "mascots.yaml").exists() else None
    )

    out = steering.remove_repo(ycfg, "alpha", keep_data=True)

    assert out["kept_data"] is True and out["cards_removed"] == 0 and out["files_removed"] == 0
    assert out["profile_removed"] is False and out["mascots_removed"] == []
    assert profile.exists()
    assert (ycfg.root / "local" / "mascots.yaml").exists() == (mascots is not None)
    new = config_mod.load_config(ycfg.root)
    assert list(new.repos) == ["beta"]
    with closing(open_db(ycfg)) as conn:
        assert rows_of(conn, "alpha", a) == before
        counts = gc.collect(conn, new, NOW)  # kept on purpose: gc leaves it
        assert counts["orphan_cards"] == 0 and rows_of(conn, "alpha", a) == before
        cards, _, _ = feed.page(conn, new, 10, None, 1, NOW)
        assert cards == []  # but the feed does not show a repo that is not configured
    # removing it again without the flag is not possible (it is not configured); adding the
    # repo again and removing it without the flag deletes the kept data
    (new.root / "local" / "repos.yaml").write_text(text(ycfg, "repos.yaml") + "")
    steering.add_repo(new, "alpha", str(new.repos["beta"].path))
    again = config_mod.load_config(ycfg.root)
    assert steering.remove_repo(again, "alpha")["cards_removed"] == 1
    with closing(open_db(ycfg)) as conn:
        assert set(rows_of(conn, "alpha", a).values()) == {0}
        assert gc.kept_repos(conn) == set()


def test_cross_repo_rule_a_card_goes_with_its_own_repo_only(ycfg):
    with closing(open_db(ycfg)) as conn:
        own = add_card(conn, ycfg, ["alpha", "beta"])  # alpha's card: removed
        cites = add_card(conn, ycfg, ["beta", "alpha"])  # beta's card that cites alpha: stays
    assert steering.remove_repo(ycfg, "alpha")["cards_removed"] == 1
    new = config_mod.load_config(ycfg.root)
    with closing(open_db(ycfg)) as conn:
        left = [r[0] for r in conn.execute("SELECT id FROM cards")]
        assert left == [cites] and own not in left
        cards, _, _ = feed.page(conn, new, 10, None, 1, NOW)
    # the card still renders: a source in the removed repo has no link, and nothing fails
    assert [c["id"] for c in cards] == [cites]
    assert [s["repo"] for s in cards[0]["sources"]] == ["beta", "alpha"]


def test_a_crash_in_the_row_delete_leaves_the_database_whole(ycfg, monkeypatch):
    with closing(open_db(ycfg)) as conn:
        a = fill(conn, ycfg, "alpha")
        before = rows_of(conn, "alpha", a)

    def boom(conn, name):
        raise RuntimeError("crash")

    monkeypatch.setattr(gc, "_delete_repo_rows", boom)
    with closing(open_db(ycfg)) as conn, pytest.raises(RuntimeError):
        gc.purge_repo(conn, ycfg, "alpha")
    with closing(open_db(ycfg)) as conn:
        assert rows_of(conn, "alpha", a) == before
    assert (ycfg.settings.data_dir / "assets" / a / "a.png").exists()  # files go after the commit


# --- mascots -------------------------------------------------------------------------------


def local_mascots(cfg, body: str) -> None:
    (cfg.root / "local" / "mascots.yaml").write_text(body)


def test_remove_repo_removes_its_own_mascot_from_the_user_file_and_its_image(ycfg):
    local_mascots(
        ycfg,
        "# my mascots\nmascots:\n  owl:\n    repo: beta\n    style: an owl   # keep?\n    seed: 3\n"
        "  fox:\n    style: a fox   # stays\n    seed: 4\n"
        "  crow:\n    repo: alpha\n    style: a crow\n    seed: 7\n",
    )
    images = ycfg.settings.data_dir / "assets" / "mascots"
    images.mkdir(parents=True)
    for n in ("owl", "fox", "crow"):
        (images / f"{n}.png").write_bytes(b"x")
    cfg = config_mod.load_config(ycfg.root)

    out = steering.remove_repo(cfg, "beta")

    assert out["mascots_removed"] == ["owl"] and out["mascots_kept"] == []
    new = config_mod.load_config(ycfg.root)
    assert sorted(new.mascots) == ["crow", "fox"]
    body = text(ycfg, "mascots.yaml")
    assert "owl" not in body and "# my mascots" in body and "# stays" in body
    assert not (images / "owl.png").exists() and (images / "fox.png").exists()


def test_the_mascot_of_the_removed_repo_goes_and_guidance_lists_none(ycfg):
    """No mascot is shipped: the one in local/mascots.yaml goes with its repo."""
    out = steering.remove_repo(ycfg, "alpha")  # crow is in local/mascots.yaml, repo alpha
    assert out["mascots_removed"] == ["crow"] and out["mascots_kept"] == []
    new = config_mod.load_config(ycfg.root)
    assert new.mascots == {}
    text_ = brief.guidance_markdown(new.personas, None, {}, new.mascots, repos=new.repos)
    assert "`crow`" not in text_ and "repo alpha" not in text_


def test_a_mascot_of_a_repo_that_is_gone_is_listed_with_no_repo(ycfg):
    local_mascots(ycfg, "mascots:\n  owl:\n    repo: gone\n    style: an owl\n")
    new = config_mod.load_config(ycfg.root)  # no error for a mascot whose repo is not there
    text_ = brief.guidance_markdown(new.personas, None, {}, new.mascots, repos=new.repos)
    assert "`owl`" in text_ and "repo gone" not in text_


def test_a_mascot_that_another_repo_uses_is_kept(ycfg):
    local_mascots(ycfg, "mascots:\n  owl:\n    repo: beta\n    style: an owl\n    seed: 3\n")
    repos = text(ycfg, "repos.yaml").replace("    mascot: crow", "    mascot: owl")
    (ycfg.root / "local" / "repos.yaml").write_text(repos)
    cfg = config_mod.load_config(ycfg.root)
    before = comments(text(cfg, "repos.yaml"))

    out = steering.remove_repo(cfg, "beta")

    assert out["mascots_removed"] == []
    assert out["mascots_kept"] == [{"name": "owl", "why": "the repo alpha uses it"}]
    new = config_mod.load_config(ycfg.root)
    assert new.mascots["owl"].repo is None  # the link to the removed repo is cleared
    assert new.repos["alpha"].mascot == "owl"
    assert comments(text(cfg, "repos.yaml")) == before


# --- gc and the feed -----------------------------------------------------------------------


def orphan(ycfg) -> config_mod.Config:
    """Take alpha out of repos.yaml by hand, as a removal before this change left it."""
    steering.remove_repo(ycfg, "alpha", keep_data=True)
    with closing(open_db(ycfg)) as conn:
        gc.set_kept(conn, "alpha", False)
        conn.commit()
    return config_mod.load_config(ycfg.root)


def test_gc_removes_cards_of_repos_that_are_not_configured(ycfg):
    with closing(open_db(ycfg)) as conn:
        a = fill(conn, ycfg, "alpha")
        b = fill(conn, ycfg, "beta")
        before_beta = rows_of(conn, "beta", b)
    new = orphan(ycfg)
    data = new.settings.data_dir
    with closing(open_db(ycfg)) as conn:
        dry = gc.collect(conn, new, NOW, dry_run=True)
        assert dry["orphan_repos"] == 1 and dry["orphan_cards"] == 1 and dry["orphan_files"] == 3
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
        assert (data / "assets" / a).is_dir()

        real = gc.collect(conn, new, NOW)

        assert {k: real[k] for k in ("orphan_repos", "orphan_cards", "orphan_files")} == {
            "orphan_repos": 1,
            "orphan_cards": 1,
            "orphan_files": 3,
        }
        assert set(rows_of(conn, "alpha", a).values()) == {0}
        assert rows_of(conn, "beta", b) == before_beta
        assert gc.collect(conn, new, NOW)["orphan_repos"] == 0
    assert not (data / "assets" / a).exists() and (data / "assets" / b).is_dir()


def test_gc_cli_prints_the_orphan_counts(ycfg, monkeypatch, capsys):
    with closing(open_db(ycfg)) as conn:
        fill(conn, ycfg, "alpha")
    orphan(ycfg)
    monkeypatch.setattr(cli, "load_config", lambda: config_mod.load_config(ycfg.root))
    assert cli.main(["gc", "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["orphan_cards"] == 1 and out["orphan_repos"] == 1


def test_feed_and_backlog_ignore_cards_of_a_repo_that_is_not_configured(ycfg):
    with closing(open_db(ycfg)) as conn:
        a = add_card(conn, ycfg, ["alpha"])
        b = add_card(conn, ycfg, ["beta"])
        quiz = add_card(conn, ycfg, ["alpha"])
        conn.execute(  # a quiz of alpha that is due for review
            "INSERT INTO srs(card_id, interval_days, due_at) VALUES (?, 1, '2026-01-01T00:00:00Z')",
            (quiz,),
        )
        conn.execute(  # alpha's card was the last one seen: a fresh load must not resume on it
            "INSERT INTO events(card_id, type, ts, data, received_at) "
            "VALUES (?, 'impression', ?, '{}', 'x')",
            (a, int(NOW.timestamp() * 1000) - 40 * 86400 * 1000),
        )
        conn.commit()
        cards, _, resume = feed.page(conn, ycfg, 10, None, 1, NOW)
        assert {a, b} <= {c["id"] for c in cards} and resume == a
    new = orphan(ycfg)
    with closing(open_db(ycfg)) as conn:
        cards, _, resume = feed.page(conn, new, 10, None, 1, NOW)
        assert [c["id"] for c in cards] == [b] and resume is None
        health = supply.feed_health(conn, new, NOW)
        assert health["backlog"] == 1 and health["by_repo"] == {"beta": 1}


# --- CLI -----------------------------------------------------------------------------------


def test_cli_prints_one_summary_line_and_has_keep_data(ycfg, fixture_repo, monkeypatch, capsys):
    with closing(open_db(ycfg)) as conn:
        fill(conn, ycfg, "alpha")
        fill(conn, ycfg, "beta")
    monkeypatch.setattr(cli, "load_config", lambda: config_mod.load_config(ycfg.root))
    assert cli.main(["repos", "remove", "beta"]) == 0
    out = capsys.readouterr().out.strip()
    assert len(out.splitlines()) == 1
    assert "removed repo beta" in out and "1 card" in out and "3 files" in out
    assert "not touched" in out
    assert cli.main(["repos", "remove", "alpha", "--keep-data"]) == 0
    out = capsys.readouterr().out.strip()
    assert "kept" in out and len(out.splitlines()) == 1
    with closing(open_db(ycfg)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    with pytest.raises(SystemExit):
        cli.main(["repos", "remove", "--help"])
    help_ = " ".join(capsys.readouterr().out.split())
    assert "never touched" in help_ and "--keep-data" in help_ and "weights" in help_
    assert fixture_repo.path.exists()


def test_gc_keeps_everything_when_no_repo_is_configured(ycfg):
    """An empty repo list is more likely a lost or broken repos.yaml than a wish to
    delete every card. The purge of unconfigured repos does nothing then."""
    from dataclasses import replace

    with closing(open_db(ycfg)) as conn:
        fill(conn, ycfg, "alpha")
        fill(conn, ycfg, "beta")
        empty = replace(ycfg, repos={})
        out = gc.collect(conn, empty, NOW)
        assert out["orphan_repos"] == 0 and out["orphan_cards"] == 0
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
