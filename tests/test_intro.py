"""Novelty drives lead ranking, and intro slots go to the least-known dirs."""

import pytest

from codescroll import brief, db, knowledge, ledger
from tests.conftest import make_config
from tests.test_brief import DEFAULTS, build
from tests.test_ledger import NOW, refresh, sig


@pytest.fixture
def conn():
    c = db.open_db(":memory:")
    yield c
    c.close()


@pytest.fixture
def cfg(fixture_repo, tmp_path):
    return make_config(fixture_repo, tmp_path)


def see(conn, dir, n, repo="r"):
    conn.execute("INSERT INTO knowledge(repo, dir, cards_seen) VALUES (?, ?, ?)", (repo, dir, n))
    conn.commit()


def test_ranked_novelty_puts_unknown_dirs_above_well_seen_ones(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py"))  # src/a.py is the stronger lead
    assert [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)][0] == "src/a.py"
    see(conn, "src", 40)
    order = [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)]
    assert order == ["lib/b.py", "src/a.py"]


def test_ranked_without_knowledge_rows_keeps_strength_order(conn, cfg):
    refresh(conn, sig("src/a.py", "lib/b.py", "docs/c.py"))
    order = [x.path for x in ledger.ranked(conn, cfg, "r", "hot_spot", NOW, 10)]
    assert order == ["src/a.py", "lib/b.py", "docs/c.py"]


def test_lead_dir_uses_deepest_known_prefix():
    nmap = {"src": 0.2, "src/deep": 0.9}
    assert knowledge.lead_dir("src/deep/x.py", nmap) == ("src/deep", 0.9)
    assert knowledge.lead_dir("src/other/x.py", nmap) == ("src", 0.2)
    assert knowledge.lead_dir("billing/api/x.py", nmap) == ("billing/api", 1.0)
    assert knowledge.lead_dir("src/deep", nmap) == ("src/deep", 0.9)  # a dir lead
    assert knowledge.lead_dir("README.md", nmap) == (None, 1.0)


def intro_leads(n_known=6, n_new=3):
    known = [
        brief.Lead(
            "hot_spot", "fixture", "path", path=f"src/f{i}.py", text=f"src/f{i}.py: hot", id=i
        )
        for i in range(n_known)
    ]
    new = [
        brief.Lead(
            "hot_spot",
            "fixture",
            "path",
            path=f"billing/g{i}.py",
            text=f"billing/g{i}.py: hot",
            id=100 + i,
        )
        for i in range(n_new)
    ]
    return known + new  # known dirs rank first


D = {"categories": {"git_drama": 1.0}, "tones": DEFAULTS["tones"]}


def test_intro_slots_reserve_share_for_least_known_dirs():
    b = build(
        count=8,
        packet_size=4,
        defaults=D,
        ledger={("fixture", "hot_spot"): intro_leads()},
        novelty={"fixture": {"src": 0.1}},
        intro_share=0.25,
    )
    refs = [r for p in b.packets for r in p.lead_refs if r.get("intro")]
    assert len([r for r in refs if r["path"].startswith("billing/")]) >= 2  # ceil(8 * 0.25)
    text = "\n".join(b.packet_markdown(p.id) for p in b.packets)
    assert "the reader has not seen billing/ yet" in text
    assert "billing/" in b.summary_markdown() and "ntro" in b.summary_markdown()


def test_intro_off_without_novelty_or_share():
    for kw in ({}, {"novelty": {"fixture": {"src": 0.1}}, "intro_share": 0.0}):
        b = build(count=8, defaults=D, ledger={("fixture", "hot_spot"): intro_leads()}, **kw)
        assert not [r for p in b.packets for r in p.lead_refs if r.get("intro")]
        assert "ntro" not in b.summary_markdown()
