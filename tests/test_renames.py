"""Leads from history name the paths of their time. A path that was renamed or deleted since
HEAD sent writers to files that are not there (path_not_at_commit) and made the brief ask for
an intro to dirs that no longer exist."""

import subprocess

from gittok import brief, signals
from tests.fixture_repo import build_history_repo

D = "2026-01-{:02d}T10:00:00+00:00"


def _git(path, *args, date=None):
    env = None
    if date:
        import os

        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)


def _renamed_repo(tmp_path):
    body = "def run():\n    return 1\n" * 5
    repo = build_history_repo(
        tmp_path / "r",
        [
            (
                "add",
                {"old/a.py": body, "old/b.py": body + "x = 2\n", "keep.py": "k = 1\n"},
                D.format(1),
            ),
            ("edit", {"old/a.py": body + "y = 3\n"}, D.format(2)),
        ],
    )
    (repo.path / "mid").mkdir()
    (repo.path / "src" / "pkg").mkdir(parents=True)
    _git(repo.path, "mv", "old/a.py", "mid/a.py")
    _git(repo.path, "commit", "-qm", "move once", date=D.format(3))
    _git(repo.path, "mv", "mid/a.py", "src/pkg/a.py")
    _git(repo.path, "rm", "-q", "old/b.py")
    _git(repo.path, "commit", "-qm", "move again, drop b", date=D.format(4))
    return repo


def test_renames_follow_a_path_to_its_name_at_head(tmp_path):
    repo = _renamed_repo(tmp_path)
    commits = signals.parse_log(repo.path, "main")
    got = signals.renames(repo.path, "main", commits)
    assert got["old/a.py"] == "src/pkg/a.py"
    assert got["mid/a.py"] == "src/pkg/a.py"
    assert got["old/b.py"] is None  # deleted
    assert "keep.py" not in got and "src/pkg/a.py" not in got  # at HEAD: not listed


def test_renames_is_a_signal(tmp_path):
    assert "renames" in signals.SIGNAL_KINDS


REN = {"old/a.py": "src/pkg/a.py", "old/b.py": None}


def test_a_path_lead_takes_the_path_at_head():
    ld = brief.Lead("hotspot", "r", "path", path="old/a.py", text="old/a.py: 9 edits")
    (out,) = brief.at_head([ld], REN)
    assert out.path == "src/pkg/a.py" and out.text == "src/pkg/a.py: 9 edits"
    assert brief.head_path(out) == "src/pkg/a.py"


def test_a_path_lead_for_a_deleted_file_is_dropped():
    ld = brief.Lead("hotspot", "r", "path", path="old/b.py", text="old/b.py: 9 edits")
    assert brief.at_head([ld], REN) == []


def test_a_commit_lead_keeps_its_path_and_says_where_it_is_now():
    ld = brief.Lead("fix", "r", "commit", commit="abc1234", path="old/a.py", text="fix on old/a.py")
    (out,) = brief.at_head([ld], REN)
    assert out.path == "old/a.py"  # true at that commit
    assert out.text == "fix on old/a.py (now at src/pkg/a.py)"
    assert brief.head_path(out) == "src/pkg/a.py"
    gone = brief.Lead("fix", "r", "commit", commit="abc1234", path="old/b.py", text="fix on b")
    (out,) = brief.at_head([gone], REN)
    assert out.text == "fix on b (gone at HEAD)" and brief.head_path(out) is None


def test_a_deleted_paths_lead_says_nothing_more():
    ld = brief.Lead("rip", "r", "commit", commit="abc1234", path="old/b.py", text="b died")
    (out,) = brief.at_head([ld], REN, story_type="rip")
    assert out.text == "b died"


def test_leads_at_head_are_unchanged():
    ld = brief.Lead("hotspot", "r", "path", path="keep.py", text="keep.py: 2 edits")
    assert brief.at_head([ld], REN) == [ld]
    assert brief.head_path(ld) == "keep.py"


def test_intro_dirs_are_dirs_at_head():
    """An intro slot for a dir that is gone asks the writer to explain code no one can see."""
    moved = brief.Lead("fix", "r", "commit", commit="abc1234", path="old/a.py", text="fix a")
    gone = brief.Lead("fix", "r", "commit", commit="abc1234", path="old/b.py", text="fix b")
    leads = brief.at_head([moved, gone], REN)
    slots = [("r", "git_drama", "fix", "text_post", None)] * 2
    ref_by = {("r", "fix"): {x.text: x for x in leads}}
    out = brief._assign_intro(slots, {}, ref_by, {"r": {}}, 1.0, 2)
    assert {d for d, _ in out.values()} == {"src/pkg"}
