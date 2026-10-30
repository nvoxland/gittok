from codescroll import gitq, signals


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
