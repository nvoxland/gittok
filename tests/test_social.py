import os
import subprocess
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest

from codescroll import db, gitq, runs, social, srs
from tests.conftest import make_config
from tests.fixture_repo import FixtureRepo

NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def make_repo(path, commits):
    """commits: list of (hours_ago, author, subject, [files]). Oldest first in git order."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }

    def git(*args, extra=None):
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=path, env={**env, **(extra or {})}, check=True, capture_output=True,
        )  # fmt: skip

    path.mkdir(parents=True)
    git("init", "-q", "-b", "main")
    for i, (hours_ago, author, subject, files) in enumerate(commits):
        for f in files:
            p = path / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"{i}\n{p.read_text() if p.exists() else ''}")
        git("add", "-A")
        date = f"{int((NOW - timedelta(hours=hours_ago)).timestamp())} +0000"
        git(
            "commit", "-q", "-m", subject,
            extra={
                "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "a@x",
                "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "a@x",
                "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
            },
        )  # fmt: skip


@pytest.fixture
def recent(tmp_path):
    repo = tmp_path / "recent"
    make_repo(
        repo,
        [
            (100, "Old Timer", "ancient", ["old.py"]),
            (5, "Ann", "first today", ["auth.py", "a.py"]),
            (3, "Bob", "second today", ["auth.py"]),
            (1, "Ann", "third today", ["auth.py", "b/c.py"]),
        ],
    )
    return repo


@pytest.fixture
def cfg(recent, tmp_path):
    return make_config(FixtureRepo(path=recent), tmp_path)


@pytest.fixture
def conn(cfg):
    c = db.open_db(cfg.settings.data_dir / "codescroll.db")
    yield c
    c.close()


@pytest.fixture(autouse=True)
def clear_cache():
    social.clear_cache()


def test_recent_commits_helper_lists_last_24h_with_files(recent):
    since = int((NOW - timedelta(hours=24)).timestamp())
    commits = gitq.recent_commits(recent, "main", since)
    assert [c["subject"] for c in commits] == ["third today", "second today", "first today"]
    assert commits[0]["author"] == "Ann"
    assert commits[0]["files"] == ["auth.py", "b/c.py"]
    assert commits[0]["ts"] == int((NOW - timedelta(hours=1)).timestamp())
    assert len(commits[0]["sha"]) == 40


def test_stories_one_per_repo_with_recent_commits(cfg, conn):
    stories = social.stories(conn, cfg, NOW)
    assert len(stories) == 1
    s = stories[0]
    assert s["repo"] == "fixture"
    assert s["mascot"] is None and s["mascot_image"] is None
    assert [c["subject"] for c in s["commits"]] == ["third today", "second today", "first today"]
    assert s["commits"][0]["files"] == 2
    assert s["commits"][0]["short"] == s["commits"][0]["sha"][:7]
    assert s["seen"] is False


def test_stories_skip_repos_without_recent_commits(fixture_repo, tmp_path, conn):
    cfg = make_config(fixture_repo, tmp_path / "other")
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        assert social.stories(c, cfg, NOW) == []


def test_stories_cap_at_ten_commits(tmp_path):
    repo = tmp_path / "busy"
    make_repo(repo, [(12 - i * 0.5, "A", f"c{i}", [f"f{i}.py"]) for i in range(12)])
    cfg = make_config(FixtureRepo(path=repo), tmp_path)
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        s = social.stories(c, cfg, NOW)[0]
    assert len(s["commits"]) == 10
    assert s["commits"][0]["subject"] == "c11"


def test_stories_seen_after_marking_every_sha(cfg, conn):
    shas = [c["sha"] for c in social.stories(conn, cfg, NOW)[0]["commits"]]
    social.mark_seen(conn, "fixture", shas[:2], NOW)
    assert social.stories(conn, cfg, NOW)[0]["seen"] is False
    social.mark_seen(conn, "fixture", shas, NOW)
    social.mark_seen(conn, "fixture", shas, NOW)  # idempotent
    assert social.stories(conn, cfg, NOW)[0]["seen"] is True


def test_stories_cached_per_head_sha(cfg, conn, monkeypatch):
    social.stories(conn, cfg, NOW)
    monkeypatch.setattr(gitq, "recent_commits", lambda *a, **k: pytest.fail("git ran"))
    assert len(social.stories(conn, cfg, NOW)) == 1


def test_stories_sorted_newest_first(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_repo(a, [(10, "A", "older", ["x.py"])])
    make_repo(b, [(2, "B", "newer", ["y.py"])])
    cfg = make_config(FixtureRepo(path=a), tmp_path)
    from dataclasses import replace

    from codescroll.config import Repo

    cfg = replace(cfg, repos={"a": Repo(name="a", path=a, ref="main"),
                              "b": Repo(name="b", path=b, ref="main")})  # fmt: skip
    with db.open_db(cfg.settings.data_dir / "codescroll.db") as c:
        assert [s["repo"] for s in social.stories(c, cfg, NOW)] == ["b", "a"]


def test_mascot_image_when_file_exists(cfg, conn):
    from dataclasses import replace

    from codescroll.config import Repo

    cfg = replace(cfg, repos={"fixture": Repo(name="fixture", path=cfg.repos["fixture"].path,
                                              ref="main", mascot="otter")})  # fmt: skip
    img = cfg.settings.data_dir / "assets" / "mascots"
    img.mkdir(parents=True)
    (img / "otter.png").write_bytes(b"x")
    s = social.stories(conn, cfg, NOW)[0]
    assert s["mascot"] == "otter"
    mtime = int((img / "otter.png").stat().st_mtime)
    assert s["mascot_image"] == f"/assets/mascots/otter.png?v={mtime}"


def finished_run(conn, cfg, accepted, repo="fixture"):
    run_id = runs.open_run(conn, cfg, repo=repo, brief="b", requested=3)
    conn.execute(
        "UPDATE runs SET status='finished', accepted=?, finished_at=? WHERE id=?",
        (accepted, "2026-10-30T11:00:00Z", run_id),
    )
    conn.commit()
    return run_id


def texts(conn, kind):
    return [r["text"] for r in conn.execute(
        "SELECT text FROM notifications WHERE kind=? ORDER BY id", (kind,))]  # fmt: skip


def test_new_cards_notification_once_per_finished_run(cfg, conn):
    finished_run(conn, cfg, 12)
    finished_run(conn, cfg, 0)
    assert social.generate_notifications(conn, cfg, NOW)["new_cards"] == 1
    assert texts(conn, "new_cards") == ["12 new cards from fixture"]
    assert social.generate_notifications(conn, cfg, NOW)["new_cards"] == 0
    assert len(texts(conn, "new_cards")) == 1


def test_new_cards_singular(cfg, conn):
    finished_run(conn, cfg, 1)
    social.generate_notifications(conn, cfg, NOW)
    assert texts(conn, "new_cards") == ["1 new card from fixture"]


def insert_card(conn, cfg, card_id, story_type, spec=None):
    run_id = runs.open_run(conn, cfg, repo="fixture", brief="b", requested=1)
    repo_id = conn.execute("SELECT id FROM repos WHERE name='fixture'").fetchone()["id"]
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec,"
        " story_key, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (card_id, run_id, repo_id, story_type, "quiz", "p", "t", db.dumps(spec or {}),
         card_id, "2026-10-30T10:00:00Z"),
    )  # fmt: skip
    conn.commit()
    return card_id


def test_srs_due_notification_once_while_unread(cfg, conn):
    cid = insert_card(conn, cfg, "q1", "commit_drama")
    assert social.generate_notifications(conn, cfg, NOW)["srs_due"] == 0
    srs._upsert(conn, cid, 1, NOW - timedelta(hours=1), 0, 0)
    conn.commit()
    assert social.generate_notifications(conn, cfg, NOW)["srs_due"] == 1
    assert texts(conn, "srs_due") == ["1 quiz card is back for another try"]
    assert social.generate_notifications(conn, cfg, NOW)["srs_due"] == 0
    conn.execute("UPDATE notifications SET read_at='x'")
    conn.commit()
    later = NOW + timedelta(hours=1)
    assert social.generate_notifications(conn, cfg, later)["srs_due"] == 0  # same due set
    cid2 = insert_card(conn, cfg, "q2", "commit_drama")
    srs._upsert(conn, cid2, 1, NOW - timedelta(hours=1), 0, 0)
    conn.commit()
    assert social.generate_notifications(conn, cfg, later)["srs_due"] == 1  # new due set


def test_hot_file_for_files_in_three_commits_once_per_day(cfg, conn):
    assert social.generate_notifications(conn, cfg, NOW)["hot_file"] == 1
    assert texts(conn, "hot_file") == ["auth.py was in 3 commits in the last 24 hours"]
    assert social.generate_notifications(conn, cfg, NOW)["hot_file"] == 0
    assert social.generate_notifications(conn, cfg, NOW + timedelta(minutes=5))["hot_file"] == 0
    key = conn.execute("SELECT dedup_key FROM notifications WHERE kind='hot_file'").fetchone()[0]
    assert str(NOW.date()) in key


def _busy_cfg(tmp_path, extra=()):
    repo = tmp_path / "busy"
    make_repo(
        repo,
        [
            (6, "Ann", "one", ["brief.py", "cli.py", "api.py", "db.py", ".beads/issues.jsonl"]),
            (5, "Ann", "two", ["brief.py", "cli.py", "api.py", "db.py", ".beads/issues.jsonl"]),
            (4, "Ann", "three", ["brief.py", "cli.py", "api.py", "db.py", ".beads/issues.jsonl"]),
            (3, "Ann", "four", ["brief.py", "cli.py", ".beads/issues.jsonl"]),
            (2, "Ann", "five", ["brief.py", ".beads/issues.jsonl"]),
            *extra,
        ],
    )
    return make_config(FixtureRepo(path=repo), tmp_path / "cfg")


def test_hot_files_in_one_repo_make_one_digest_without_dot_dirs(tmp_path):
    cfg = _busy_cfg(tmp_path)
    with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
        assert social.generate_notifications(conn, cfg, NOW)["hot_file"] == 1
        (text,) = texts(conn, "hot_file")
    assert text.startswith("Busy day in ")
    assert text.endswith(": brief.py (5 commits), cli.py (4), api.py (3) and 1 more")
    assert "issues.jsonl" not in text


def test_more_commits_to_a_hot_file_the_same_day_do_not_notify_again(tmp_path):
    cfg = _busy_cfg(tmp_path, extra=[(1, "Ann", "six", ["brief.py", "cli.py"])])
    with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
        social.generate_notifications(conn, cfg, NOW - timedelta(minutes=90))
        social.clear_cache()
        assert social.generate_notifications(conn, cfg, NOW)["hot_file"] == 0
        assert social.generate_notifications(conn, cfg, NOW + timedelta(days=1))["hot_file"] == 0
        assert len(texts(conn, "hot_file")) == 1


def test_new_kind_for_spot_the_bug_card(cfg, conn):
    insert_card(conn, cfg, "s1", "spot_the_bug", {"dirs": ["billing"]})
    insert_card(conn, cfg, "o1", "commit_drama", {"dirs": ["billing"]})
    assert social.generate_notifications(conn, cfg, NOW)["new_kind"] == 1
    row = conn.execute("SELECT * FROM notifications WHERE kind='new_kind'").fetchone()
    assert row["text"] == "A new Spot the Bug from billing/"
    assert row["card_id"] == "s1"
    assert social.generate_notifications(conn, cfg, NOW)["new_kind"] == 0


def test_new_kind_ignores_cards_older_than_24h(cfg, conn):
    insert_card(conn, cfg, "old", "spot_the_bug", {"dirs": ["billing"]})
    conn.execute("UPDATE cards SET created_at='2026-10-20T10:00:00Z' WHERE id='old'")
    conn.commit()
    assert social.generate_notifications(conn, cfg, NOW)["new_kind"] == 0


def test_list_and_mark_read(cfg, conn):
    finished_run(conn, cfg, 3)
    social.generate_notifications(conn, cfg, NOW)
    out = social.list_notifications(conn, unread_only=True)
    assert out["unread"] == 2  # new_cards + hot_file
    first = out["notifications"][0]
    assert set(first) == {"id", "kind", "text", "card_id", "created_at", "read", "repo"}
    hot = next(n for n in out["notifications"] if n["kind"] == "hot_file")
    assert hot["repo"] == "fixture"
    social.mark_read(conn, ids=[first["id"]], now=NOW)
    assert social.list_notifications(conn, unread_only=True)["unread"] == 1
    assert len(social.list_notifications(conn)["notifications"]) == 2
    social.mark_read(conn, all=True, now=NOW)
    out = social.list_notifications(conn, unread_only=True)
    assert out == {"notifications": [], "unread": 0}


def test_lan_urls_use_given_addresses():
    assert social.lan_urls(8008, ["192.168.1.5", "10.0.0.2"]) == [
        "http://192.168.1.5:8008", "http://10.0.0.2:8008"]  # fmt: skip


def test_lan_addresses_are_non_loopback_ipv4():
    addrs = social.lan_addresses()
    assert all(a.count(".") == 3 and not a.startswith("127.") for a in addrs)
    assert len(addrs) == len(set(addrs))


# --- hot file notifications link to cards -------------------------------


def _notif(conn, kind="hot_file"):
    return conn.execute("SELECT * FROM notifications WHERE kind = ?", (kind,)).fetchone()


def _notif_leads(conn):
    return conn.execute("SELECT COUNT(*) FROM leads WHERE lead_key LIKE 'notif:%'").fetchone()[0]


def _add_card_row(conn, cfg, card_id, path, created_at, lead_id=None):
    from codescroll import store

    repo_id = store.ensure_repo(conn, cfg.repos["fixture"])
    conn.execute("INSERT INTO runs(id, status, started_at) VALUES ('rx', 'finished', 'x')")
    spec = {"repos": ["fixture"], "sources": [{"repo": "fixture", "path": path, "lines": [1, 2]}]}
    conn.execute(
        "INSERT INTO cards(id, run_id, repo_id, story_type, format, persona, tone, spec, resolved, "
        "status, story_key, created_at, lead_id) VALUES (?, 'rx', ?, 'before_after', 'text', 'p', "
        "'t', ?, '{}', 'ready', ?, ?, ?)",
        (card_id, repo_id, db.dumps(spec), f"k{card_id}", created_at, lead_id),
    )
    conn.commit()


def test_hot_file_without_card_makes_a_notif_lead_and_submit_links_it(cfg, conn):
    from codescroll import ledger

    social.generate_notifications(conn, cfg, NOW)
    n = _notif(conn)
    assert n["card_id"] is None
    lead = conn.execute("SELECT * FROM leads WHERE lead_key = ?", (f"notif:{n['id']}",)).fetchone()
    assert (lead["story_type"], lead["kind"], lead["path"], lead["strength"]) == (
        "before_after", "commit", "auth.py", 2.0,
    )  # fmt: skip
    since = int((NOW - timedelta(hours=24)).timestamp())
    head = gitq.recent_commits(cfg.repos["fixture"].path, "main", since)[0]["sha"]
    assert lead["commit_sha"] == head
    assert lead["text"] == (
        "today's hot file: auth.py was in 3 commits in the last 24 hours. "
        "Explain what changed and why it matters."
    )
    social.generate_notifications(conn, cfg, NOW + timedelta(minutes=5))  # no second lead
    assert _notif_leads(conn) == 1
    _add_card_row(conn, cfg, "c_new", "auth.py", "2026-10-30T12:30:00Z", lead_id=lead["id"])
    with db.immediate(conn):
        ledger.mark_covered(conn, lead["id"], NOW)
    assert _notif(conn)["card_id"] == "c_new"
    assert _notif(conn)["read_at"] is None


def test_notif_lead_is_offered_first(cfg, conn):
    from codescroll import ledger

    social.generate_notifications(conn, cfg, NOW)
    out = ledger.for_brief(conn, cfg, ["fixture"], NOW)
    assert out[("fixture", "before_after")][0].key.startswith("notif:")


def test_hot_file_with_a_recent_card_links_directly_without_a_lead(cfg, conn):
    _add_card_row(conn, cfg, "c_old", "auth.py", "2026-10-30T02:00:00Z")
    social.generate_notifications(conn, cfg, NOW)
    assert _notif(conn)["card_id"] == "c_old"
    assert _notif_leads(conn) == 0


def test_hot_file_ignores_cards_older_than_a_day(cfg, conn):
    _add_card_row(conn, cfg, "c_old", "auth.py", "2026-10-28T02:00:00Z")
    social.generate_notifications(conn, cfg, NOW)
    assert _notif(conn)["card_id"] is None
    assert _notif_leads(conn) == 1
