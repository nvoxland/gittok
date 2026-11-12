from dataclasses import replace

from blamescroll import materials
from blamescroll.brief import Lead
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo

WHY_BODY = " ".join(f"reason{i}" for i in range(40))  # 40 words
_D = "2026-01-05T10:00:00+00:00"


def _ref(**kw):
    return Lead(**{"story_type": "x", "repo": "fixture", "kind": "none", **kw}).__dict__


def _why_repo(tmp_path, subject="Rework parser"):
    steps = [
        ("add parser", {"p.py": "a = 1\n"}, _D),
        ("tweak", {"p.py": "a = 2\n"}, "2026-01-06T10:00:00+00:00"),
        (f"{subject}\n\n{WHY_BODY}", {"p.py": "a = 3\n"}, "2026-01-07T10:00:00+00:00"),
    ]
    return build_history_repo(tmp_path / "r", steps)


def test_path_lead_has_why_it_changed_with_long_body(tmp_path):
    fr = _why_repo(tmp_path)
    cfg = make_config(fr, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="path", path="p.py"))
    assert "Why it changed" in text
    why = text.split("Why it changed", 1)[1]
    assert "reason0" in why and "reason39" in why
    assert fr.shas["2"][:7] in why and "2026-01-07" in why and "Rework parser" in why
    assert "tweak" not in why  # short body, no issue ref


def test_why_commits_filters_and_limits(tmp_path):
    fr = _why_repo(tmp_path)
    cfg = make_config(fr, tmp_path)
    got = materials.why_commits(cfg, "fixture", "p.py")
    assert [c["sha"] for c in got] == [fr.shas["2"]]
    assert got[0]["subject"] == "Rework parser" and WHY_BODY in got[0]["body"]
    assert materials.why_commits(cfg, "fixture", "p.py", limit=0) == []
    assert materials.why_commits(cfg, "fixture", "missing.py") == []


def test_why_ranks_longest_body_then_newest(tmp_path):
    short = " ".join(["w"] * 30)
    long = " ".join(["w"] * 60)
    steps = [
        (f"a\n\n{short}", {"p.py": "1\n"}, "2026-01-01T10:00:00+00:00"),
        (f"b\n\n{long}", {"p.py": "2\n"}, "2026-01-02T10:00:00+00:00"),
        (f"c\n\n{short}", {"p.py": "3\n"}, "2026-01-03T10:00:00+00:00"),
        (f"d\n\n{short}", {"p.py": "4\n"}, "2026-01-04T10:00:00+00:00"),
    ]
    fr = build_history_repo(tmp_path / "r", steps)
    cfg = make_config(fr, tmp_path)
    got = materials.why_commits(cfg, "fixture", "p.py")
    assert [c["subject"] for c in got] == ["b", "d", "c"]


def test_why_body_is_trimmed(tmp_path):
    big = " ".join(["word"] * 400)
    fr = build_history_repo(tmp_path / "r", [(f"s\n\n{big}", {"p.py": "a\n"}, _D)])
    cfg = make_config(fr, tmp_path)
    (c,) = materials.why_commits(cfg, "fixture", "p.py")
    assert len(c["body"]) <= materials.WHY_BODY_CHARS + 5


def test_pr_ref_in_subject_links_only_with_github_remote(tmp_path):
    fr = _why_repo(tmp_path, subject="Rework parser (#12)")
    cfg = make_config(fr, tmp_path)
    assert "/pull/12" not in materials.materials_for(cfg, _ref(kind="path", path="p.py"))
    repo = replace(cfg.repos["fixture"], url="https://github.com/acme/fixture")
    cfg2 = replace(cfg, repos={"fixture": repo})
    text = materials.materials_for(cfg2, _ref(kind="path", path="p.py"))
    assert "https://github.com/acme/fixture/pull/12" in text


def test_short_body_with_pr_subject_still_counts(tmp_path):
    fr = build_history_repo(tmp_path / "r", [("Fix it (#7)", {"p.py": "a\n"}, _D)])
    cfg = make_config(fr, tmp_path)
    assert [c["subject"] for c in materials.why_commits(cfg, "fixture", "p.py")] == ["Fix it (#7)"]


def test_commit_lead_includes_body(tmp_path):
    fr = _why_repo(tmp_path)
    cfg = make_config(fr, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="commit", commit=fr.shas["2"]))
    assert "reason0" in text and "reason39" in text


def test_why_section_does_not_break_caps(tmp_path):
    body = "".join(f"line {i} " + "x" * 60 + "\n" for i in range(1, 101))
    msg = " ".join(["why"] * 500)
    steps = [
        (f"s{i}\n\n{msg}", {"a.txt": body + f"{i}\n"}, f"2026-01-0{i + 1}T10:00:00+00:00")
        for i in range(5)
    ]
    fr = build_history_repo(tmp_path / "r", steps)
    cfg = make_config(fr, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="path", path="a.txt"))
    assert len(text.encode()) <= materials.LEAD_CAP + len(materials.MARKER) + 2
    assert "1\tline 1" in text  # the code window survives
    assert text.count("Why it changed") <= 1
