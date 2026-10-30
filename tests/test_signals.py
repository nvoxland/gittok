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
