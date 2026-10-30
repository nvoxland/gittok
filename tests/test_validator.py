import pytest

from codescroll import validator
from codescroll.config import Repo
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def check(cards, repos):
    return validator.validate_cards(cards, repos, PERSONAS)


def reasons(rejected):
    return [r.reason for r in rejected]


def test_rejects_lines_out_of_range(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["lines"] = [3, 99]
    accepted, rejected = check([card], repos)
    assert accepted == []
    assert reasons(rejected) == ["lines_out_of_range"]
    assert rejected[0].index == 0


def test_accepts_valid_card_and_resolves_code(fixture_repo, repos):
    accepted, rejected = check([example_card(fixture_repo)], repos)
    assert rejected == []
    [a] = accepted
    assert a.card["visual"]["commit"] == fixture_repo.shas["invoice_add"]
    assert a.resolved["visual"]["code"].startswith("def total(items):")
    assert a.resolved["visual"]["language"] == "python"
    assert a.resolved["visual"]["start_line"] == 1
    assert a.resolved["depth"][0] is None
    assert "+    return round(t, 2)" in a.resolved["depth"][1]["diff"]
    assert len(a.story_key) == 16


def test_dirs_accept_plain_and_repo_prefixed(fixture_repo, repos):
    for dirs in (["billing"], ["fixture/billing"], ["src", "billing/"], []):
        accepted, rejected = check([example_card(fixture_repo, dirs=dirs)], repos)
        assert rejected == [], dirs


def test_rejects_unknown_dir(fixture_repo, repos):
    for dirs in (["nope"], ["fixture/nope"], ["src/app.py"]):
        _, rejected = check([example_card(fixture_repo, dirs=dirs)], repos)
        assert reasons(rejected) == ["unknown_dir"], dirs


def _mutate(fixture_repo, fn):
    card = example_card(fixture_repo)
    fn(card, fixture_repo.shas)
    return card


MUTATIONS = {
    "schema": lambda c, s: c.update(tone="smug"),
    "unknown_repo": lambda c, s: c.update(repos=["fixture", "other"]),
    "unknown_commit": lambda c, s: c["visual"].update(commit="abcdef1234"),
    "commit_not_in_ref": lambda c, s: c["visual"].update(commit=s["unmerged"]),
    "path_not_at_commit": lambda c, s: c["visual"].update(commit=s["initial"]),
    "excerpt_too_long": lambda c, s: (
        c["visual"].update(path="data/big.txt", commit=s["huge"], lines=[1, 41]),
        c["visual"].pop("callouts"),
    ),
    "callout_out_of_range": lambda c, s: c["visual"]["callouts"][0].update(line=9),
    # src/app.py did not change in the commit that deleted legacy.py
    "empty_diff": lambda c, s: c["depth"][1].update(commit=s["delete_legacy"], path="src/app.py"),
    "missing_explain_panel": lambda c, s: c.update(depth=c["depth"][1:]),
    "excerpt_mismatch": lambda c, s: c["visual"].update(excerpt="def total(items):\n    pass"),
}


@pytest.mark.parametrize("reason", sorted(MUTATIONS))
def test_reject_reasons(fixture_repo, repos, reason):
    card = _mutate(fixture_repo, MUTATIONS[reason])
    accepted, rejected = check([card], repos)
    assert accepted == []
    assert reasons(rejected) == [reason], rejected[0].detail


def test_excerpt_matching_ignores_trailing_space_and_tabs(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["visual"]["excerpt"] = (
        "\ndef total(items):   \n    t = 0\n\tfor price in items:\n"
        "        t += price\n    return round(t)\n\n"
    )
    accepted, rejected = check([card], repos)
    assert rejected == []
    assert accepted[0].resolved["visual"]["code"].splitlines()[2] == "    for price in items:"


def test_source_path_checked_at_repo_ref(fixture_repo, repos):
    card = example_card(fixture_repo)
    card["sources"] = [{"repo": "fixture", "path": "src/legacy.py"}]
    _, rejected = check([card], repos)
    assert reasons(rejected) == ["path_not_at_commit"]


def test_duplicate_story_in_same_submission(fixture_repo, repos):
    accepted, rejected = check([example_card(fixture_repo), example_card(fixture_repo)], repos)
    assert len(accepted) == 1
    assert [(r.index, r.reason) for r in rejected] == [(1, "duplicate_story")]


def test_one_bad_card_does_not_block_others(fixture_repo, repos):
    bad = example_card(fixture_repo, persona="nobody")
    accepted, rejected = check([bad, text_card(fixture_repo)], repos)
    assert [a.index for a in accepted] == [1]
    assert [r.index for r in rejected] == [0]


def test_input_card_not_mutated(fixture_repo, repos):
    card = example_card(fixture_repo)
    short = card["visual"]["commit"]
    check([card], repos)
    assert card["visual"]["commit"] == short
