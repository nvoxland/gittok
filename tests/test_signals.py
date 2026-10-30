from pathlib import Path

import pytest

from codescroll import db, gitq, signals
from codescroll.config import AnalysisSettings, Repo


def test_churn_ranks_most_edited_file_first(fixture_repo):
    t0 = gitq.commit_time(fixture_repo.path, "main")
    commits = signals.parse_log(fixture_repo.path, "main")
    out = signals.churn(commits, t0)
    top = out["files"]["365"]
    # app.py and util.py tie on commits (7); util.py has more changed lines (16 vs 15).
    assert top[0] == {"path": "src/util.py", "commits": 7, "lines": 16}
    assert top[1] == {"path": "src/app.py", "commits": 7, "lines": 15}


def test_numstat_line_binary_has_none_counts():
    assert signals._parse_numstat("-\t-\timg.png") == signals.FileChange("img.png", None, None)
    assert signals._parse_numstat("3\t1\tsrc/a.py") == signals.FileChange("src/a.py", 3, 1)
    assert signals._parse_numstat("") is None


def test_parse_log_excludes_merge_and_unmerged(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    shas = [c.sha for c in commits]
    assert fixture_repo.shas["merge"] not in shas
    assert fixture_repo.shas["unmerged"] not in shas
    assert fixture_repo.shas["feature_commit"] in shas
    assert shas[0] == fixture_repo.shas["head"]  # newest first
    assert all(len(c.parents) == 1 for c in commits[:-1])


def test_churn_dirs_and_root_and_window(fixture_repo):
    t0 = gitq.commit_time(fixture_repo.path, "main")
    commits = signals.parse_log(fixture_repo.path, "main")
    out = signals.churn(commits, t0)
    dirs = {d["path"]: d for d in out["dirs"]["365"]}
    assert dirs["src"]["commits"] == 9  # one count per commit touching the dir
    assert dirs["."]["commits"] == 1  # README.md in initial commit
    # 30-day window: cutoff = 2026-01-21T15:00Z; only commits from Jan 25 on
    files30 = [f["path"] for f in out["files"]["30"]]
    assert "billing/invoice.py" not in files30
    assert "src/util.py" in files30


def test_co_change_finds_app_util_pair(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    pairs = signals.co_change(commits)
    assert pairs == [
        {"a": "src/app.py", "b": "src/util.py", "count": 7, "jaccard": 1.0, "same_dir": True}
    ]


def test_co_change_skips_big_commits_and_singletons():
    def c(sha, *paths):
        return signals.Commit(
            sha, (), 0, 0, "x", "x@x", "s", tuple(signals.FileChange(p, 1, 0) for p in paths)
        )

    commits = [c("1", "a", "b"), c("2", "a", "b"), c("3", "a", "b", "d/c"), c("4", "a")]
    assert signals.co_change(commits, min_count=3, max_files=2) == []
    out = signals.co_change(commits, min_count=2, max_files=20)
    assert out[0] == {"a": "a", "b": "b", "count": 3, "jaccard": 0.75, "same_dir": True}
    assert {"a": "a", "b": "d/c", "count": 1} not in out


def test_author_shares_by_top_level_dir(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    by_dir = signals.author_shares(commits)["by_dir"]
    assert by_dir["src"] == [
        {"author": "Alice Archer", "commits": 6, "lines": 25, "share": 0.676},
        {"author": "Bob Builder", "commits": 3, "lines": 12, "share": 0.324},
    ]
    assert by_dir["."] == [{"author": "Alice Archer", "commits": 1, "lines": 1, "share": 1.0}]
    assert by_dir["data"][0]["author"] == "Bob Builder"
    assert by_dir["billing"] == [{"author": "Bob Builder", "commits": 3, "lines": 9, "share": 1.0}]


def test_commit_times_finds_late_night(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    out = signals.commit_times(commits)
    assert len(out["hour_histogram"]) == 24
    assert sum(out["hour_histogram"]) == len(commits) == 13
    assert out["hour_histogram"][2] == 1
    assert out["hour_histogram"][11] == 3  # invoice_add, fix1, fix2
    assert out["late_night"] == [
        {
            "sha": fixture_repo.shas["late_night"],
            "author": "Alice Archer",
            "local_hour": 2,
            "subject": "Speed up parsing",
            "ts": 1768185000,
        }
    ]
    assert out["late_by_author"] == {"Alice Archer": 1}


def test_huge_diffs_finds_import_commit(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    out = signals.huge_diffs(commits)
    assert len(out) == 1
    assert out[0]["sha"] == fixture_repo.shas["huge"]
    assert out[0]["lines"] == 1200
    assert out[0]["files"] == 1
    assert out[0]["author"] == "Bob Builder"
    assert out[0]["subject"] == "Import fixtures"
    assert signals.huge_diffs(commits, threshold=1200) == []


def test_new_files_lists_additions_newest_first(fixture_repo):
    out = signals.new_files(fixture_repo.path, "main", None)
    by_path = {r["path"]: r for r in out}
    inv = by_path["billing/invoice.py"]
    assert inv["sha"] == fixture_repo.shas["invoice_add"]
    assert inv["author"] == "Bob Builder"
    assert inv["subject"] == "Add invoice totals"
    assert "src/new_feature.py" in by_path
    assert "billing/experiment.py" not in by_path
    assert [r["ts"] for r in out] == sorted((r["ts"] for r in out), reverse=True)
    recent = signals.new_files(fixture_repo.path, "main", 1769000000)  # after 2026-01-21
    assert {r["path"] for r in recent} == {"src/new_feature.py", "data/big.txt"}


def test_revert_links_to_reverted_commit(fixture_repo):
    out = signals.reverts(fixture_repo.path, "main")
    assert len(out) == 1
    r = out[0]
    assert r["sha"] == fixture_repo.shas["revert"]
    assert r["reverted_sha"] == fixture_repo.shas["feature_flag"]
    assert r["reverted_subject"] == "Add feature flag"
    assert r["subject"] == 'Revert "Add feature flag"'


def test_fix_chain_on_invoice(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    chains = signals.fix_chains(commits)
    by_path = {c["path"]: c for c in chains}
    chain = by_path["billing/invoice.py"]
    assert [c["sha"] for c in chain["commits"]] == [
        fixture_repo.shas["fix1"],
        fixture_repo.shas["fix2"],
    ]
    assert chain["commits"][0]["author"] == "Bob Builder"
    assert chain["commits"][0]["subject"] == "fix rounding in invoice"


def test_deleted_path_has_birth_and_lifetime(fixture_repo):
    out = signals.deleted_paths(fixture_repo.path, "main")
    row = next(r for r in out if r["path"] == "src/legacy.py")
    assert row["born_sha"] == fixture_repo.shas["initial"]
    assert row["died_sha"] == fixture_repo.shas["delete_legacy"]
    assert row["cause"] == "Remove legacy module, replaced by util"
    assert row["died_author"] == "Bob Builder"
    assert row["born_author"] == "Alice Archer"
    assert row["lived_days"] == 20


def test_deleted_paths_accepts_precomputed_added(fixture_repo):
    added = {"src/legacy.py": {"sha": "abc", "ts": 0, "author": "Zed"}}
    out = signals.deleted_paths(fixture_repo.path, "main", added=added)
    row = next(r for r in out if r["path"] == "src/legacy.py")
    assert row["born_sha"] == "abc"
    assert row["born_author"] == "Zed"


def test_commits_since_lists_new_commits(fixture_repo):
    s = fixture_repo.shas
    out = signals.commits_since(fixture_repo.path, "main", s["cochange3"])
    assert out["base"] == s["cochange3"]
    assert out["count"] == 1
    assert out["commits"][0]["sha"] == s["head"]
    assert out["commits"][0]["author"] == "Bob Builder"


def test_commits_since_unknown_or_missing_base(fixture_repo):
    empty = {"base": None, "count": None, "commits": []}
    assert signals.commits_since(fixture_repo.path, "main", None) == empty
    assert signals.commits_since(fixture_repo.path, "main", "0" * 40) == empty
    # exists, but is not an ancestor of main
    assert signals.commits_since(fixture_repo.path, "main", fixture_repo.shas["unmerged"]) == empty


def test_oldest_todo_has_age_from_blame(fixture_repo):
    out = signals.todo_ages(fixture_repo.path, "main")
    first = out[0]
    assert first["path"] == "src/util.py"
    assert first["line"] == 1
    assert first["tag"] == "TODO"
    assert first["author"] == "Alice Archer"
    assert first["sha"] == fixture_repo.shas["initial"]
    assert first["ts"] == 1767607200  # 2026-01-05T10:00Z
    assert "replace this parser" in first["text"]


def test_oldest_lines_returns_oldest_line_per_file(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    out = signals.oldest_lines(fixture_repo.path, "main", commits)
    paths = [r["path"] for r in out]
    assert "README.md" not in paths  # not source-like
    assert len(paths) == len(set(paths))
    assert [r["ts"] for r in out] == sorted(r["ts"] for r in out)  # oldest first
    first = out[0]
    assert first["path"] == "src/app.py"
    assert first["line"] == 1
    assert first["text"] == "def main():"
    assert first["sha"] == fixture_repo.shas["initial"]
    assert first["author"] == "Alice Archer"


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(tmp_path / "t.db")
    yield c
    c.close()


def _repo(fixture_repo) -> Repo:
    return Repo(name="fixture", path=Path(fixture_repo.path), ref="main", mascot="owl")


@pytest.fixture
def git_calls(monkeypatch):
    """Record the args of every git subprocess call (all go through gitq.run_bytes)."""
    calls: list[tuple[str, ...]] = []
    real = gitq.run_bytes

    def spy(repo, *args, **kw):
        calls.append(args)
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitq, "run_bytes", spy)
    return calls


def test_analyze_skips_when_head_unchanged(conn, fixture_repo, git_calls):
    repo = _repo(fixture_repo)
    first = signals.analyze(conn, repo, AnalysisSettings())
    assert first["cached"] is False
    assert first["head_sha"] == fixture_repo.shas["head"]
    assert set(first["signals"]) == set(signals.SIGNAL_KINDS)

    git_calls.clear()
    second = signals.analyze(conn, repo, AnalysisSettings())
    assert second["cached"] is True
    assert second["signals"] == first["signals"]
    assert second["head_sha"] == first["head_sha"] and second["t0"] == first["t0"]
    # Only rev_parse (resolve head) and commit_time (rev_parse + log -1 --format=%ct).
    assert [c[0] for c in git_calls] == ["rev-parse", "rev-parse", "log"]
    assert git_calls[2][:3] == ("log", "-1", "--format=%ct")


def test_analyze_force_recomputes(conn, fixture_repo, git_calls):
    repo = _repo(fixture_repo)
    first = signals.analyze(conn, repo, AnalysisSettings())
    git_calls.clear()
    forced = signals.analyze(conn, repo, AnalysisSettings(), force=True)
    assert forced["cached"] is False
    assert any(c[0] == "log" and "--numstat" in c for c in git_calls)
    assert forced["signals"]["churn"] == first["signals"]["churn"]
    n = conn.execute("SELECT COUNT(*) FROM git_signals").fetchone()[0]
    assert n == len(signals.SIGNAL_KINDS)  # INSERT OR REPLACE, no duplicates


def test_analyze_windows_are_relative_to_t0_not_wall_clock(conn, fixture_repo):
    out = signals.analyze(conn, _repo(fixture_repo), AnalysisSettings())
    assert out["t0"] == 1771599600  # 2026-02-20T15:00Z, months before wall-clock today
    files30 = [f["path"] for f in out["signals"]["churn"]["files"]["30"]]
    assert files30  # non-empty
    assert "src/util.py" in files30
    assert "billing/invoice.py" not in files30


def test_payloads_round_trip_and_load_signals(conn, fixture_repo):
    import json

    assert signals.load_signals(conn, "fixture") is None
    out = signals.analyze(conn, _repo(fixture_repo), AnalysisSettings())
    assert json.loads(json.dumps(out["signals"])) == out["signals"]
    loaded = signals.load_signals(conn, "fixture")
    assert loaded == out["signals"]
    assert loaded["reverts"][0]["reverted_sha"] == fixture_repo.shas["feature_flag"]
    assert loaded["todo_ages"][0]["tag"] == "TODO"
    row = conn.execute("SELECT duration_ms FROM git_signals WHERE kind='churn'").fetchone()
    assert row["duration_ms"] is not None


def test_commits_since_after_unchanged_head_is_empty(conn, fixture_repo):
    repo = _repo(fixture_repo)
    first = signals.analyze(conn, repo, AnalysisSettings())
    assert first["signals"]["commits_since"] == {"base": None, "count": None, "commits": []}
    again = signals.analyze(conn, repo, AnalysisSettings(), force=True)
    cs = again["signals"]["commits_since"]
    assert cs["base"] == again["head_sha"]
    assert cs["count"] == 0


def test_analyze_holds_no_write_lock_during_git_work(conn, fixture_repo, monkeypatch, tmp_path):
    seen = {}
    real = signals.todo_ages

    def probe(*a, **k):
        other = db.connect(tmp_path / "t.db")
        other.execute("PRAGMA busy_timeout=0")
        try:
            other.execute(
                "INSERT INTO events(type, ts, data, received_at) VALUES ('x', 1, '{}', 't')"
            )
            other.commit()
            seen["wrote"] = True
        except Exception as e:  # noqa: BLE001
            seen["wrote"] = repr(e)
        finally:
            other.close()
        return real(*a, **k)

    monkeypatch.setattr(signals, "todo_ages", probe)
    signals.analyze(conn, _repo(fixture_repo), AnalysisSettings())
    assert seen["wrote"] is True


def test_analyze_git_error_midway_leaves_db_unchanged(conn, fixture_repo, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise gitq.GitError("boom")

    monkeypatch.setattr(signals, "todo_ages", boom)
    with pytest.raises(gitq.GitError):
        signals.analyze(conn, _repo(fixture_repo), AnalysisSettings())
    other = db.connect(tmp_path / "t.db")
    assert other.execute("SELECT COUNT(*) FROM repos").fetchone()[0] == 0
    assert other.execute("SELECT COUNT(*) FROM git_signals").fetchone()[0] == 0
    other.close()


def _git_env():
    import os

    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }


class TinyRepo:
    """A throwaway repo driven with plain git; `day` counts days after 2026-01-01."""

    def __init__(self, path):
        import subprocess

        self.path = path
        path.mkdir(parents=True)
        self._run = lambda *a, env=None: subprocess.run(
            ["git", "-C", str(path), *a], check=True, capture_output=True, env=env or _git_env()
        )
        self._run("init", "-q", "-b", "main")

    def write(self, name, text):
        p = self.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg, day):
        stamp = f"2026-01-{day:02d}T12:00:00+00:00"
        env = {**_git_env(), "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        self._run("add", "-A")
        self._run("commit", "-q", "-m", msg, env=env)
        return self._run("rev-parse", "HEAD").stdout.decode().strip()

    def git(self, *a):
        self._run(*a)


@pytest.fixture
def tiny(tmp_path):
    return TinyRepo(tmp_path / "tiny")


BODY = "".join(f"line {i} of a reasonably long file\n" for i in range(20))


def test_rename_is_neither_new_nor_deleted(tiny):
    tiny.write("a.py", BODY)
    tiny.write("b.py", BODY + "different\n" * 5)
    tiny.commit("add a and b", 1)
    (tiny.path / "moved").mkdir()
    tiny.git("mv", "a.py", "moved/a.py")
    tiny.commit("move a", 2)
    tiny.git("rm", "-q", "b.py")
    tiny.commit("remove b", 3)
    assert [r["path"] for r in signals.deleted_paths(tiny.path, "main")] == ["b.py"]
    paths = [r["path"] for r in signals.new_files(tiny.path, "main", None)]
    assert sorted(paths) == ["a.py", "b.py"]  # moved/a.py is not new


def test_readded_path_lifetime_uses_latest_add_before_death(tiny):
    tiny.write("x.py", BODY)
    tiny.commit("add x", 1)
    tiny.git("rm", "-q", "x.py")
    tiny.commit("rm x", 2)
    tiny.write("x.py", BODY)
    readd = tiny.commit("re-add x", 10)
    tiny.git("rm", "-q", "x.py")
    tiny.commit("rm x again", 15)
    rows = signals.deleted_paths(tiny.path, "main")
    by_day = sorted(rows, key=lambda r: r["died_ts"])
    assert [r["lived_days"] for r in by_day] == [1, 5]
    assert by_day[1]["born_sha"] == readd


def test_oldest_lines_finds_old_file_outside_history_window(tiny):
    tiny.write("old.py", "ANCIENT = 1\n")
    tiny.commit("add old", 1)
    for i in range(8):
        tiny.write(f"new{i}.py", f"v = {i}\n")
        tiny.commit(f"add new{i}", 10 + i)
        tiny.write(f"new{i}.py", f"v = {i}\nw = 2\n")
        tiny.commit(f"edit new{i}", 20 + i % 5)
    day10 = int(
        __import__("datetime").datetime(2026, 1, 9, tzinfo=__import__("datetime").UTC).timestamp()
    )
    commits = signals.parse_log(tiny.path, "main", day10)
    assert "old.py" not in {f.path for c in commits for f in c.files}
    rows = signals.oldest_lines(tiny.path, "main", commits, max_files=4)
    assert rows[0]["path"] == "old.py"
    assert rows[0]["text"] == "ANCIENT = 1"


def test_todo_ages_handles_colons_in_paths(tiny):
    tiny.write("we:ird/a:b.py", "x = 1\n# TODO fix this\n")
    tiny.write("plain.py", "# FIXME later\n")
    tiny.commit("add", 1)
    rows = signals.todo_ages(tiny.path, "main")
    assert {(r["path"], r["line"], r["tag"]) for r in rows} == {
        ("we:ird/a:b.py", 2, "TODO"),
        ("plain.py", 1, "FIXME"),
    }


def test_todo_ages_skips_file_whose_blame_fails(tiny, monkeypatch):
    tiny.write("good.py", "# TODO ok\n")
    tiny.write("bad.py", "# TODO nope\n")
    tiny.commit("add", 1)
    real = gitq.run_bytes

    def flaky(repo, *args, **kw):
        if args[0] == "blame" and args[-1] == "bad.py":
            raise gitq.GitError("blame exploded")
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitq, "run_bytes", flaky)
    rows = signals.todo_ages(tiny.path, "main")
    assert [r["path"] for r in rows] == ["good.py"]


# --- recent_commits -------------------------------------------------------


def test_recent_commits_last_30_days_newest_first(fixture_repo):
    t0 = gitq.commit_time(fixture_repo.path, "main")
    commits = signals.parse_log(fixture_repo.path, "main")
    rows = signals.recent_commits(commits, t0)
    s = fixture_repo.shas
    assert [r["sha"] for r in rows] == [
        s["head"], s["cochange3"], s["huge"], s["feature_commit"], s["delete_legacy"],
    ]  # fmt: skip
    top = rows[0]
    assert set(top) == {"sha", "ts", "author", "subject", "files"}
    assert top["author"] == "Bob Builder"
    assert top["subject"] == "Tweak helper and join again"
    assert top["files"] == ["src/app.py", "src/util.py"]


def test_recent_commits_caps_commits_and_files():
    many = tuple(signals.FileChange(f"f{i}.py", 1, 0) for i in range(30))
    commits = [
        signals.Commit(f"{i:040x}", (), 1000 + i, 12, "A", "a@x", f"c{i}", many) for i in range(250)
    ]
    rows = signals.recent_commits(commits, 2000)
    assert len(rows) == 200
    assert rows[0]["ts"] == 1249  # newest first
    assert len(rows[0]["files"]) == 20


def test_analyze_stores_recent_commits_and_recomputes_old_cache(conn, fixture_repo):
    repo = _repo(fixture_repo)
    first = signals.analyze(conn, repo, AnalysisSettings())
    assert len(first["signals"]["recent_commits"]) == 5
    conn.execute("DELETE FROM git_signals WHERE kind = 'recent_commits'")
    conn.commit()
    assert signals.load_signals(conn, repo.name).get("recent_commits") is None
    again = signals.analyze(conn, repo, AnalysisSettings())
    assert again["cached"] is False  # an old analysis without the kind is recomputed
    assert again["signals"]["recent_commits"] == first["signals"]["recent_commits"]


def test_analyze_reports_group_path_and_ref_for_cross_repo_leads(conn, fixture_repo):
    repo = Repo(name="fixture", path=fixture_repo.path, ref="main", group="dev")
    for cached in (False, True):
        res = signals.analyze(conn, repo, AnalysisSettings())
        assert res["cached"] is cached
        assert res["group"] == "dev"
        assert res["path"] == str(fixture_repo.path)


def test_fix_hunks_name_first_parent_and_old_side_ranges(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    hunks = signals.fix_hunks(fixture_repo.path, signals.fix_chains(commits))
    fix2 = fixture_repo.shas["fix2"]
    entry = next(h for h in hunks if h["sha"] == fix2 and h["path"] == "billing/invoice.py")
    assert entry["parent"] == gitq.first_parent(fixture_repo.path, fix2)
    assert entry["ranges"] == [
        list(r) for r in gitq.changed_old_ranges(fixture_repo.path, fix2, "billing/invoice.py")
    ]
    assert entry["ranges"]


def test_fix_hunks_respects_limit(fixture_repo):
    commits = signals.parse_log(fixture_repo.path, "main")
    assert signals.fix_hunks(fixture_repo.path, signals.fix_chains(commits), limit=1) == [
        signals.fix_hunks(fixture_repo.path, signals.fix_chains(commits))[0]
    ]


def test_analyze_stores_fix_hunks(conn, fixture_repo):
    out = signals.analyze(conn, _repo(fixture_repo), AnalysisSettings())
    assert any(h["sha"] == fixture_repo.shas["fix1"] for h in out["signals"]["fix_hunks"])
