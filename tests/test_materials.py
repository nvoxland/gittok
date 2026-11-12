import subprocess

from gittok import materials
from gittok.brief import Lead
from tests.conftest import make_config
from tests.fixture_repo import build_history_repo


def _ref(**kw):
    return Lead(**{"story_type": "x", "repo": "fixture", "kind": "none", **kw}).__dict__


def test_commit_lead_materials_have_subject_stat_and_capped_diff(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="commit", commit=fixture_repo.shas["huge"]))
    assert "Import fixtures" in text
    assert "Bob Builder" in text
    assert "2026-02-10" in text
    assert "data/big.txt" in text  # in --stat
    diff = text.split("```diff", 1)[1].split("```", 1)[0]
    assert diff.count("\n") <= 82  # 80 lines plus the fence newlines
    assert "row 0" in diff

    small = materials.materials_for(cfg, _ref(kind="commit", commit=fixture_repo.shas["fix1"]))
    assert "fix rounding in invoice" in small
    assert "-    return round(t)" in small and "+    return round(t, 2)" in small


def test_commit_stat_lists_at_most_15_files(tmp_path):
    files = {f"f{i:02d}.py": "x = 1\n" for i in range(20)}
    fr = build_history_repo(tmp_path / "r", [("many", files, "2026-01-05T10:00:00+00:00")])
    cfg = make_config(fr, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="commit", commit=fr.shas["0"]))
    assert "f14.py" in text and "f15.py" not in text
    assert "5 more" in text


def test_path_lead_materials_have_blob_sha_numbered_lines_and_blame(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="path", path="billing/invoice.py"))
    assert "billing/invoice.py" in text
    blob = subprocess.run(
        ["git", "-C", str(fixture_repo.path), "rev-parse", "main:billing/invoice.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert blob[:10] in text
    assert "1\tdef total(items):" in text
    assert "Bob Builder" in text and "100%" in text
    assert "2026-01-15" in text and "2026-01-17" in text  # first and last commit

    around = materials.materials_for(cfg, _ref(kind="path", path="src/util.py", lines=[3, 3]))
    assert "3\t" in around


def test_path_lead_window_centers_on_lines(tmp_path):
    body = "".join(f"line {i}\n" for i in range(1, 201))
    fr = build_history_repo(tmp_path / "r", [("big", {"a.txt": body}, "2026-01-05T10:00:00+00:00")])
    cfg = make_config(fr, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="path", path="a.txt", lines=[100, 100]))
    assert "100\tline 100" in text and "70\tline 70" in text
    assert "40\tline 40" not in text and "131\tline 131" not in text


def test_none_lead_has_no_materials(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    assert materials.materials_for(cfg, _ref(kind="none")) == ""


def test_bad_coordinates_do_not_raise(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    assert materials.materials_for(cfg, _ref(kind="path", path="nope.py")) == ""
    assert materials.materials_for(cfg, _ref(kind="commit", commit="0" * 40)) == ""


def test_packet_materials_cap(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    one = materials.materials_for(cfg, _ref(kind="commit", commit=fixture_repo.shas["huge"]))
    assert len(one.encode()) <= materials.LEAD_CAP
    refs = [
        _ref(story_type=f"t{i}", kind="path", path="data/big.txt", lines=[i, i])
        for i in range(1, 1200, 10)
    ]
    out = materials.packet_materials(cfg, refs)
    assert len(out.encode()) <= materials.PACKET_CAP + 100
    assert "[truncated]" in out


def test_packet_materials_cover_only_top_leads_per_story_type(fixture_repo, tmp_path):
    """A writer uses 1-2 leads per story type; materials for the rest only bloat get_packet."""
    cfg = make_config(fixture_repo, tmp_path)
    refs = [
        _ref(story_type=t, kind="path", path="data/big.txt", lines=[i, i], text=f"{t} lead {i}")
        for t in ("rip", "hot_spot")
        for i in (1, 11, 21, 31, 41)
    ]
    out = materials.packet_materials(cfg, refs)
    heads = [line for line in out.splitlines() if line.startswith("### ")]
    assert heads == [
        "### [rip] rip lead 1",
        "### [rip] rip lead 11",
        "### [hot_spot] hot_spot lead 1",
        "### [hot_spot] hot_spot lead 11",
    ]
    assert len(out.encode()) <= materials.PACKET_CAP <= 12 * 1024


def _callers_repo(tmp_path):
    files = {
        "lib/tax.py": "import os\nfrom decimal import Decimal\n\n\ndef compute_tax(x):\n"
        "    return x * 2\n\n\nclass Taxer:\n    pass\n",
        "a.py": "from lib.tax import compute_tax\nprint(compute_tax(1))\n",
        "b.py": "def go():\n    return compute_tax(2)\n",
        "c.py": "y = compute_tax(3)\n",
        "tests/test_tax.py": "assert compute_tax(4) == 8\n",
    }
    fr = build_history_repo(tmp_path / "r", [("tax", files, "2026-01-05T10:00:00+00:00")])
    return make_config(fr, tmp_path)


def test_explain_lead_lists_defines_callers_and_imports(tmp_path):
    cfg = _callers_repo(tmp_path)
    lead = _ref(story_type="what_it_does", kind="path", path="lib/tax.py")
    text = materials.materials_for(cfg, lead)
    assert "Defines:" in text and "compute_tax" in text.split("Defines:")[1].split("\n\n")[0]
    assert "Taxer" in text.split("Defines:")[1].split("\n\n")[0]
    called = text.split("Called from:")[1].split("\n\n")[0].splitlines()[1:]
    paths = [ln.split(": ")[0] for ln in called if ln.strip()]
    assert paths[:3] == ["a.py:1", "a.py:2", "b.py:2"] or {
        "a.py:2",
        "b.py:2",
        "c.py:1",
    } <= set(paths)
    assert paths[-1].startswith("tests/")  # test files last
    assert not any(p.startswith("lib/tax.py") for p in paths)  # own definition skipped
    assert "Imports:" in text and "import os" in text.split("Imports:")[1]
    assert text.index("Defines:") < text.index("Called from:") < text.index("Imports:")


def test_non_explain_story_type_has_no_called_from(tmp_path):
    cfg = _callers_repo(tmp_path)
    text = materials.materials_for(cfg, _ref(story_type="rip", kind="path", path="lib/tax.py"))
    assert "Called from:" not in text and "Defines:" not in text


def test_explain_lead_cap_is_larger_and_respected(tmp_path):
    cfg = _callers_repo(tmp_path)
    text = materials.materials_for(
        cfg, _ref(story_type="what_it_does", kind="path", path="lib/tax.py")
    )
    assert len(text.encode()) <= materials.EXPLAIN_LEAD_CAP > materials.LEAD_CAP


def _store_facts(cfg, repo_path):
    """A definition and a call in billing/invoice.py lines 1-3, as the facts store holds them."""
    from contextlib import closing

    from gittok import db

    with closing(db.open_db(cfg.settings.data_dir / "gittok.db")) as conn:
        conn.execute(
            "INSERT INTO repos(name, path, ref) VALUES ('fixture', ?, 'main')", (str(repo_path),)
        )
        rid = conn.execute("SELECT id FROM repos WHERE name = 'fixture'").fetchone()[0]
        conn.execute(
            "INSERT INTO fact_defines VALUES ('def-aaaaaaaaaaaa', ?, 'billing/invoice.py',"
            " 'invoice/total', 'total', 'function', 1, 3, 3, 1, 0, 0, 1, 'analyzer:kit 1')", (rid,)
        )  # fmt: skip
        conn.execute(
            "INSERT INTO fact_calls VALUES ('call-bbbbbbbbbbbb', ?, 'invoice/total', 'round',"
            " 'billing/invoice.py', 2, 0, NULL, 'syntax')", (rid,)
        )  # fmt: skip
        conn.commit()


def test_path_lead_lists_fact_ids_for_its_window(fixture_repo, tmp_path):
    """writers never called the fact tools, so the packet hands them the ids."""
    cfg = make_config(fixture_repo, tmp_path)
    _store_facts(cfg, fixture_repo.path)
    text = materials.materials_for(cfg, _ref(kind="path", path="billing/invoice.py", lines=[1, 3]))
    assert "Facts in these lines" in text
    assert "def-aaaaaaaaaaaa" in text and "total" in text
    assert "call-bbbbbbbbbbbb" in text and "round" in text


def test_path_lead_without_stored_facts_has_no_facts_section(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    text = materials.materials_for(cfg, _ref(kind="path", path="billing/invoice.py", lines=[1, 3]))
    assert "Facts in these lines" not in text
