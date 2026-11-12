from __future__ import annotations

import os
import subprocess

import pytest

from gittok import research
from gittok.config import (
    AgentSettings,
    AnalysisSettings,
    Config,
    Repo,
    ResearchSettings,
    ServerSettings,
    Settings,
)
from gittok.research import ResearchError


def make_cfg(repo_path, **research_kw) -> Config:
    settings = Settings(
        data_dir=repo_path / "data",
        server=ServerSettings(),
        agent=AgentSettings(),
        analysis=AnalysisSettings(),
        research=ResearchSettings(**research_kw),
    )
    return Config(
        root=repo_path,
        repos={"fix": Repo(name="fix", path=repo_path, ref="main")},
        groups={},
        settings=settings,
        defaults={},
        personas={},
    )


@pytest.fixture
def cfg(fixture_repo):
    return make_cfg(fixture_repo.path)


def test_read_file_refuses_path_outside_repo(cfg):
    for bad in ("../etc/passwd", "/etc/passwd"):
        with pytest.raises(ResearchError):
            research.read_file(cfg, "fix", bad)


def test_read_file_numbers_lines_from_git(cfg):
    out = research.read_file(cfg, "fix", "src/app.py")
    assert out.splitlines()[0] == "1\tdef main():"
    assert "2\t    print('hello')" in out


def test_unknown_repo_lists_known_names(cfg):
    with pytest.raises(ResearchError, match="fix"):
        research.read_file(cfg, "nope", "README.md")


def test_read_file_normalizes_dot_slash(cfg):
    assert research.read_file(cfg, "fix", "./src/app.py").startswith("1\tdef main():")


@pytest.mark.parametrize("bad", ["-rf", "a/../b", "a\0b", "src/.."])
def test_read_file_rejects_odd_paths(cfg, bad):
    with pytest.raises(ResearchError):
        research.read_file(cfg, "fix", bad)


def test_read_file_missing_path_is_short_error(cfg):
    with pytest.raises(ResearchError, match=r"path not found at main: nope\.py"):
        research.read_file(cfg, "fix", "nope.py")


def test_read_file_bad_ref_is_research_error(cfg):
    for bad in ("--output=x", "a b", "nonexistent-branch"):
        with pytest.raises(ResearchError):
            research.read_file(cfg, "fix", "README.md", ref=bad)


def test_read_file_binary_refused(cfg, monkeypatch):
    real = research.gitq.run_bytes

    def fake(repo, *args, **kw):
        if args and args[0] == "cat-file":
            return 0, b"abc\x00def\n"
        return real(repo, *args, **kw)

    monkeypatch.setattr(research.gitq, "run_bytes", fake)
    with pytest.raises(ResearchError, match="binary"):
        research.read_file(cfg, "fix", "src/app.py")


def test_read_file_caps_lines_with_note(fixture_repo):
    cfg = make_cfg(fixture_repo.path, max_read_lines=5)
    out = research.read_file(cfg, "fix", "data/big.txt")
    lines = out.splitlines()
    assert lines[:5] == [f"{i}\trow {i - 1}" for i in range(1, 6)]
    assert lines[5] == "… file has 1200 lines; pass lines=[a,b]"
    assert len(lines) == 6


def test_read_file_lines_span_is_capped(fixture_repo):
    cfg = make_cfg(fixture_repo.path, max_read_lines=5)
    out = research.read_file(cfg, "fix", "data/big.txt", lines=(10, 100))
    assert out.splitlines() == [f"{i}\trow {i - 1}" for i in range(10, 15)]


def test_read_file_lines_invalid_span(cfg):
    for bad in ((0, 3), (5, 2)):
        with pytest.raises(ResearchError):
            research.read_file(cfg, "fix", "src/app.py", lines=bad)


def test_read_file_at_older_ref(cfg, fixture_repo):
    out = research.read_file(cfg, "fix", "src/app.py", ref=fixture_repo.shas["initial"])
    assert "helper" not in out


def test_read_file_truncates_at_max_output_bytes(fixture_repo):
    cfg = make_cfg(fixture_repo.path, max_output_bytes=40)
    out = research.read_file(cfg, "fix", "data/big.txt")
    assert out.endswith("[truncated]")
    assert len(out) < 200


def test_read_file_on_directory_points_to_list_dir(cfg):
    with pytest.raises(ResearchError, match="list_dir"):
        research.read_file(cfg, "fix", "src")


def test_list_dir_dirs_first_with_slash(cfg):
    assert research.list_dir(cfg, "fix").splitlines() == [
        "billing/",
        "data/",
        "src/",
        "README.md",
    ]


def test_list_dir_subdir_and_ref(cfg, fixture_repo):
    now = research.list_dir(cfg, "fix", "src")
    assert now.splitlines() == ["app.py", "new_feature.py", "util.py"]
    old = research.list_dir(cfg, "fix", "./src/", ref=fixture_repo.shas["initial"])
    assert old.splitlines() == ["app.py", "legacy.py", "util.py"]


def test_list_dir_errors(cfg):
    with pytest.raises(ResearchError, match="path not found at main: nope"):
        research.list_dir(cfg, "fix", "nope")
    with pytest.raises(ResearchError):
        research.list_dir(cfg, "fix", "../x")
    with pytest.raises(ResearchError, match="read_file"):
        research.list_dir(cfg, "fix", "README.md")


def test_git_grep_strips_ref_prefix(cfg):
    out = research.git_grep(cfg, "fix", "def helper", pathspec="src")
    assert out == "src/app.py:4:def helper():"


def test_git_grep_no_matches(cfg):
    assert research.git_grep(cfg, "fix", "zzz_not_there") == "no matches"


def test_git_grep_caps_hits(cfg):
    out = research.git_grep(cfg, "fix", "^row", pathspec="data", limit=3)
    lines = out.splitlines()
    assert lines[:3] == [
        "data/big.txt:1:row 0",
        "data/big.txt:2:row 1",
        "data/big.txt:3:row 2",
    ]
    assert lines[3] == "… 1197 more"


def test_git_grep_pattern_is_not_an_option(cfg):
    assert research.git_grep(cfg, "fix", "--output=x") == "no matches"
    assert research.git_grep(cfg, "fix", "--output=x", fixed=True) == "no matches"


def test_git_grep_fixed_vs_regex(cfg):
    assert research.git_grep(cfg, "fix", "round(t", fixed=True).startswith("billing/")
    with pytest.raises(ResearchError, match="grep"):
        research.git_grep(cfg, "fix", "round(t")


def test_git_log_line_format(cfg, fixture_repo):
    out = research.git_log(cfg, "fix", limit=2)
    head = fixture_repo.shas["head"][:7]
    assert out.splitlines()[0] == f"{head} 2026-02-20 Bob Builder Tweak helper and join again"
    assert len(out.splitlines()) == 2


def test_git_log_path_since_grep(cfg):
    by_path = research.git_log(cfg, "fix", path="billing/invoice.py")
    assert [ln.split(" ", 4)[-1] for ln in by_path.splitlines()] == [
        "fix rounding again",
        "fix rounding in invoice",
        "Add invoice totals",
    ]
    since = research.git_log(cfg, "fix", since="2026-02-10")
    assert len(since.splitlines()) == 3  # huge, cochange3, head
    hit = research.git_log(cfg, "fix", grep="FIX ROUNDING")
    assert len(hit.splitlines()) == 2


def test_git_log_ref_and_errors(cfg, fixture_repo):
    out = research.git_log(cfg, "fix", ref="unmerged", limit=1)
    assert "Experiment, never merged" in out
    with pytest.raises(ResearchError):
        research.git_log(cfg, "fix", path="../x")
    with pytest.raises(ResearchError):
        research.git_log(cfg, "fix", ref="--all")


def test_git_log_max_is_capped_and_validated(cfg):
    with pytest.raises(ResearchError, match="limit"):
        research.git_log(cfg, "fix", limit=0)


def test_git_log_empty_result(cfg):
    assert research.git_log(cfg, "fix", grep="zzz-no-such-commit") == "no commits"


def test_git_log_bad_since_is_research_error(cfg):
    with pytest.raises(ResearchError):
        research.git_log(cfg, "fix", since="--output=x")


def test_git_show_header_and_patch(cfg, fixture_repo):
    sha = fixture_repo.shas["fix1"]
    out = research.git_show(cfg, "fix", sha)
    assert out.startswith(f"commit {sha}")
    assert "Bob Builder" in out and "2026-01-16" in out
    assert "fix rounding in invoice" in out
    assert "+    return round(t, 2)" in out


def test_git_show_stat_and_path_limit(cfg, fixture_repo):
    sha = fixture_repo.shas["cochange1"]
    stat = research.git_show(cfg, "fix", sha, stat=True)
    assert "src/app.py" in stat and "src/util.py" in stat
    assert "@@" not in stat
    limited = research.git_show(cfg, "fix", sha, path="src/util.py")
    assert "src/util.py" in limited and "src/app.py" not in limited


def test_git_show_rejects_bad_commit_and_path(cfg):
    for bad in ("--output=x", "nope123", "a b"):
        with pytest.raises(ResearchError):
            research.git_show(cfg, "fix", bad)
    with pytest.raises(ResearchError):
        research.git_show(cfg, "fix", "HEAD", path="/etc/passwd")


def test_git_blame_range(cfg, fixture_repo):
    out = research.git_blame(cfg, "fix", "src/app.py", lines=(1, 2))
    rows = out.splitlines()
    assert len(rows) == 2
    assert fixture_repo.shas["initial"][:7] in rows[0]
    assert "2026-01-05" in rows[0] and "def main():" in rows[0]


def test_git_blame_defaults_to_capped_span(fixture_repo):
    cfg = make_cfg(fixture_repo.path, max_read_lines=5)
    assert len(research.git_blame(cfg, "fix", "data/big.txt").splitlines()) == 5
    assert len(research.git_blame(cfg, "fix", "data/big.txt", lines=(1, 99)).splitlines()) == 5


def test_git_blame_short_file_and_errors(cfg):
    assert len(research.git_blame(cfg, "fix", "src/app.py").splitlines()) == 5
    with pytest.raises(ResearchError, match="path not found at main: nope.py"):
        research.git_blame(cfg, "fix", "nope.py")
    with pytest.raises(ResearchError):
        research.git_blame(cfg, "fix", "../x")


def test_tools_never_write(cfg, fixture_repo):
    repo = fixture_repo.path
    index = repo / ".git" / "index"

    def status() -> str:
        return subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            # Without this, the check itself may refresh the index ("racy git").
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        ).stdout

    before_status, before_mtime = status(), index.stat().st_mtime_ns
    sha = fixture_repo.shas["head"]
    research.git_log(cfg, "fix")
    research.git_show(cfg, "fix", sha)
    research.git_show(cfg, "fix", sha, stat=True)
    research.git_blame(cfg, "fix", "src/app.py")
    research.git_grep(cfg, "fix", "helper")
    research.read_file(cfg, "fix", "src/app.py")
    research.list_dir(cfg, "fix", "src")
    assert status() == before_status
    assert index.stat().st_mtime_ns == before_mtime


def test_read_file_empty_or_dir_path_points_to_list_dir(cfg):
    for p in ("", ".", "src", "src/"):
        with pytest.raises(ResearchError, match="list_dir"):
            research.read_file(cfg, "fix", p)


def test_git_log_and_show_treat_path_literally(cfg, fixture_repo):
    assert research.git_log(cfg, "fix", path="src/*.py") == "no commits"
    assert research.git_log(cfg, "fix", path=":(glob)**/*.py") == "no commits"
    out = research.git_show(cfg, "fix", fixture_repo.shas["cochange1"], path="src/*.py")
    assert "diff --git" not in out


def test_git_grep_pathspec_allows_glob(cfg):
    out = research.git_grep(cfg, "fix", "def helper", pathspec="src/*.py")
    assert "src/app.py" in out


def test_read_file_numbers_lines_by_newline_only(tmp_path):
    from tests.fixture_repo import build_small_repo

    fr = build_small_repo(tmp_path / "r", {"a.txt": b"one\x0ctwo\nthree\r\nfour\n"})
    out = research.read_file(make_cfg(fr.path), "fix", "a.txt")
    assert out.split("\n") == ["1\tone\x0ctwo", "2\tthree", "3\tfour"]


def test_bad_lines_argument_is_research_error(cfg):
    for bad in ([5], [1, 2, 3], [], "ab"):
        with pytest.raises(ResearchError, match="lines"):
            research.read_file(cfg, "fix", "src/app.py", lines=bad)
        with pytest.raises(ResearchError, match="lines"):
            research.git_blame(cfg, "fix", "src/app.py", lines=bad)


def test_blame_range_past_end_is_not_path_not_found(cfg):
    with pytest.raises(ResearchError, match="past end|has 5 lines") as e:
        research.git_blame(cfg, "fix", "src/app.py", lines=[50, 60])
    assert "not found" not in str(e.value)


def test_dot_pathspec_means_whole_repo(cfg):
    for dot in (".", "./"):
        assert "src/app.py" in research.git_grep(cfg, "fix", "def helper", pathspec=dot)
        assert research.git_log(cfg, "fix", path=dot) != "no commits"
        assert "diff --git" in research.git_show(cfg, "fix", "main", path=dot)


def test_git_grep_limit_must_be_positive(cfg):
    for n in (0, -1):
        with pytest.raises(ResearchError, match="limit"):
            research.git_grep(cfg, "fix", "def", limit=n)
