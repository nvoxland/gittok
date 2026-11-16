"""Line numbers follow git: "\\n" only. Form feeds and U+2028 do not start a line."""

from gittok import candidates, conventions, gitq
from tests.fixture_repo import build_history_repo

ODD = "a = 1  \x0c b\nline2   mid\nline3\x85x\nline4\n"


def _repo(tmp_path):
    return build_history_repo(
        tmp_path / "r", [("one", {"m.py": ODD}, "2026-01-01T10:00:00+00:00")]
    )


def test_window_hashes_count_lines_like_git(tmp_path):
    r = _repo(tmp_path)
    items = [{"path": "m.py", "start": 4, "end": 4}]
    got = candidates.window_hashes(r.path, "main", items)
    assert got[("m.py", 4, 4)] == candidates.window_hash(["line4"])


def test_convention_texts_count_lines_like_git(tmp_path):
    r = _repo(tmp_path)
    texts = conventions._texts(r.path, "main", {"m.py"})
    assert len(texts["m.py"]) == 4


def test_scout_window_uses_git_lines():
    assert gitq.split_lines(ODD)[3] == "line4"
