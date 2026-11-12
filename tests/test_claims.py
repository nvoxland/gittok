"""Claim checks: checkable tokens in card prose must match git."""

import pytest

from blamescroll import claims, validator
from blamescroll.config import Repo
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


@pytest.fixture
def repos(fixture_repo):
    return {"fixture": Repo(name="fixture", path=fixture_repo.path, ref="main")}


def run(cards, repos, **kw):
    return validator.validate_cards(cards, repos, PERSONAS, **kw)


def signals(commits=101, lines=480):
    return lambda name: {
        "churn": {
            "files": {"90": [{"path": "billing/invoice.py", "commits": commits, "lines": lines}]},
            "dirs": {"90": [{"path": "billing", "commits": commits + 5, "lines": lines}]},
        }
    }


def card_with(fixture_repo, hook=None, **overrides):
    card = example_card(fixture_repo, **overrides)
    if hook:
        card["hook"] = hook
    return card


def reject(rejected):
    assert [r.reason for r in rejected] == ["claim_unverified"], rejected
    return rejected[0].detail


# --- counts -----------------------------------------------------------------


def test_wrong_commit_count_is_rejected(fixture_repo, repos):
    card = card_with(fixture_repo, hook="billing/invoice.py had 999 commits in 90 days.")
    _, rejected = run([card], repos, signals_for=signals())
    detail = reject(rejected)
    assert "999" in detail and "hook" in detail
    assert "cite the commit or path that shows it, or remove it" in detail


def test_signal_commit_count_passes(fixture_repo, repos):
    card = card_with(fixture_repo, hook="billing/invoice.py had 101 commits in 90 days.")
    accepted, rejected = run([card], repos, signals_for=signals())
    assert rejected == [] and len(accepted) == 1


def test_signal_lines_changed_passes(fixture_repo, repos):
    card = card_with(fixture_repo, hook="That file saw 480 lines changed in 90 days.")
    accepted, rejected = run([card], repos, signals_for=signals())
    assert rejected == [], rejected


def test_lead_text_number_passes(fixture_repo, repos):
    card = card_with(fixture_repo, hook="billing/invoice.py had 77 commits.")
    _, rejected = run([card], repos)
    reject(rejected)
    lead = ["billing/invoice.py: 77 commits, 300 lines changed (90d)"]
    accepted, rejected = run([card], repos, lead_texts=lead)
    assert rejected == [], rejected


def test_file_length_passes(fixture_repo, repos):
    card = card_with(fixture_repo, hook="The file data/big.txt has 1200 lines.")
    card["sources"].append({"repo": "fixture", "path": "data/big.txt", "lines": [1, 3]})
    accepted, rejected = run([card], repos)
    assert rejected == [], rejected


def test_small_numbers_versions_percent_and_code_do_not_trigger(fixture_repo, repos):
    hooks = [
        "Three commits and 12 files changed in one go.",
        "Version 2.14.0 changed 70% of the 20-odd tests.",
        "Reads `99 commits` as a string and `120 lines` too.",
        "Bumped to v18 in 2024, then again.",
        "Over 100 commits touched it, roughly.",
    ]
    for hook in hooks:
        accepted, rejected = run([card_with(fixture_repo, hook=hook)], repos)
        assert rejected == [], (hook, rejected)


# --- line references --------------------------------------------------------


def test_line_references_inside_the_file_pass(fixture_repo, repos):
    card = card_with(fixture_repo, hook="Line 5 of invoice.py rounds; lines 1-5 sum it.")
    accepted, rejected = run([card], repos)
    assert rejected == [], rejected


def test_line_reference_past_end_of_file_is_rejected(fixture_repo, repos):
    card = card_with(fixture_repo, hook="Line 400 of invoice.py rounds the total.")
    _, rejected = run([card], repos)
    assert "line 400" in reject(rejected).lower()


# --- dates ------------------------------------------------------------------


def test_correct_date_passes(fixture_repo, repos):
    # fix1 was committed 2026-01-16
    for hook in ("Fixed on 2026-01-16.", "Fixed on Jan 16, 2026.", "Fixed 16 January 2026."):
        accepted, rejected = run([card_with(fixture_repo, hook=hook)], repos)
        assert rejected == [], (hook, rejected)


def test_date_within_a_day_passes(fixture_repo, repos):
    accepted, rejected = run([card_with(fixture_repo, hook="Fixed on 2026-01-17.")], repos)
    assert rejected == [], rejected


def test_wrong_date_is_rejected(fixture_repo, repos):
    _, rejected = run([card_with(fixture_repo, hook="Born 2023-09-01 and never fixed.")], repos)
    detail = reject(rejected)
    assert "2023-09-01" in detail and "hook" in detail


def test_wrong_long_date_is_rejected(fixture_repo, repos):
    _, rejected = run([card_with(fixture_repo, hook="Born Sep 1, 2023.")], repos)
    assert "Sep 1, 2023" in reject(rejected)


def test_date_in_lead_text_passes(fixture_repo, repos):
    card = card_with(fixture_repo, hook="Born 2023-09-01.")
    accepted, rejected = run([card], repos, lead_texts=["created 2023-09-01 by Alice"])
    assert rejected == [], rejected


def test_deleted_file_dates_come_from_its_history(fixture_repo, repos):
    # the card cites only the deleting commit (01-25); the birth date comes from legacy.py's log
    hook = "RIP legacy.py, 2026-01-05 to 2026-01-25."
    accepted, rejected = run([text_card(fixture_repo, hook=hook)], repos)
    assert rejected == [], rejected
    _, rejected = run(
        [text_card(fixture_repo, hook="RIP legacy.py, 2025-03-05 to 2026-01-25.")], repos
    )
    assert "2025-03-05" in reject(rejected)


# --- identifiers and paths --------------------------------------------------


def test_invented_backticked_name_is_rejected(fixture_repo, repos):
    card = card_with(fixture_repo, hook="`hosted-instance-env` decides the rounding.")
    detail = reject(run([card], repos)[1])
    assert "hosted-instance-env" in detail and "hook" in detail


def test_real_names_and_paths_pass(fixture_repo, repos):
    for hook in (
        "`total` loops over `items`.",
        "`billing/invoice.py` rounds; `invoice.py` too.",
        "`round(t, 2)` fixed it, see `total()`.",
        "`billing/` holds money code.",
        "Run `git log -3` or `--force` or `x = 1` or `true`.",
        "Uses `parse` from `src/util.py`.",
    ):
        accepted, rejected = run([card_with(fixture_repo, hook=hook)], repos)
        assert rejected == [], (hook, rejected)


def test_name_elsewhere_in_repo_passes(fixture_repo, repos):
    # a path the card does not cite still counts when it exists at the ref
    card = card_with(fixture_repo, hook="`src/new_feature.py` came in by merge.")
    accepted, rejected = run([card], repos)
    assert rejected == [], rejected


def test_invented_name_in_explain_comment_callout_and_visual(fixture_repo, repos):
    card = card_with(fixture_repo)
    card["depth"][0]["text"] += "\n\nAlso `fetch_user_profile` is called here."
    assert "explain" in reject(run([card], repos)[1])
    card = card_with(fixture_repo)
    card["comments"][0]["text"] = "Why not `make_money_work`?"
    assert "comment" in reject(run([card], repos)[1])
    card = card_with(fixture_repo)
    card["visual"]["callouts"][0]["text"] = "see `ghost_function` here"
    assert "callout" in reject(run([card], repos)[1])
    card = text_card(fixture_repo)
    card["visual"]["body"] = "It called `phantom_call`."
    assert "visual" in reject(run([card], repos)[1])


# --- shas -------------------------------------------------------------------


def test_real_sha_passes_and_fake_sha_is_rejected(fixture_repo, repos):
    real = fixture_repo.shas["fix2"][:9]
    accepted, rejected = run([card_with(fixture_repo, hook=f"Fixed again in {real}.")], repos)
    assert rejected == [], rejected
    _, rejected = run([card_with(fixture_repo, hook="Fixed again in 1a2b3c4d5.")], repos)
    assert "1a2b3c4d5" in reject(rejected)


def test_hex_looking_words_are_not_shas(fixture_repo, repos):
    hook = "A defaced facade, a decade of effaced code."
    accepted, rejected = run([card_with(fixture_repo, hook=hook)], repos)
    assert rejected == [], rejected


# --- switch -----------------------------------------------------------------


def test_claim_checks_false_disables_the_pass(fixture_repo, repos):
    card = card_with(fixture_repo, hook="Born 2023-09-01, `ghost-fn`, 999 commits.")
    assert reject(run([card], repos)[1])
    accepted, rejected = run([card], repos, claim_checks=False)
    assert rejected == [] and len(accepted) == 1


def test_other_reasons_come_first(fixture_repo, repos):
    card = card_with(fixture_repo, hook="Born 2023-09-01.")
    card["visual"]["lines"] = [3, 99]
    assert [r.reason for r in run([card], repos)[1]] == ["lines_out_of_range"]


def test_agent_setting_defaults_on():
    from blamescroll.config import AgentSettings

    assert AgentSettings().claim_checks is True


# --- extraction units -------------------------------------------------------


def test_count_claims_skips_hedges_ranges_and_line_refs():
    assert claims.count_claims("It saw 101 commits and 1,200 lines changed.") == [101, 1200]
    assert claims.count_claims("about 101 commits, over 50 files, lines 36-60") == []
    assert claims.count_claims("12 commits, 3 files, line 40 changed, 99% of files") == []
