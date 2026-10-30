import copy

import pytest

from codescroll import validator
from tests.cards import example_card, text_card

PERSONAS = ["greybeard", "penny_learns", "archivist", "meme_compiler", "paranoid_sec", "shipit_sam"]


def errors(card):
    return validator.schema_errors(card, PERSONAS)


def test_example_card_passes_schema(fixture_repo):
    assert errors(example_card(fixture_repo)) == []


def test_text_card_passes_schema(fixture_repo):
    assert errors(text_card(fixture_repo)) == []


def test_unknown_story_type_rejected(fixture_repo):
    errs = errors(example_card(fixture_repo, story_type="mystery"))
    assert errs and "story_type" in errs[0]


def test_unknown_persona_rejected(fixture_repo):
    assert errors(example_card(fixture_repo, persona="linus"))


def test_comment_persona_must_be_known(fixture_repo):
    card = example_card(fixture_repo, comments=[{"persona": "Real Person", "text": "hi"}])
    assert errors(card)


def test_additional_properties_rejected(fixture_repo):
    card = example_card(fixture_repo)
    card["visual"]["secret"] = 1
    assert errors(card)


@pytest.mark.parametrize("kind", ["meme", "illustration", "chart", "diagram", "template"])
def test_m2_visual_kinds_not_yet_allowed(fixture_repo, kind):
    assert errors(example_card(fixture_repo, visual={"kind": kind}))


def test_depth_required_and_bounded(fixture_repo):
    assert errors(example_card(fixture_repo, depth=[]))
    five = [{"kind": "explain", "text": "x"}] * 5
    assert errors(example_card(fixture_repo, depth=five))


def test_lines_must_be_pair_of_positive_ints(fixture_repo):
    card = example_card(fixture_repo)
    bad = copy.deepcopy(card)
    bad["visual"]["lines"] = [0, 3]
    assert errors(bad)
    bad["visual"]["lines"] = [1, 2, 3]
    assert errors(bad)


def test_commit_must_look_like_sha(fixture_repo):
    card = example_card(fixture_repo)
    card["visual"]["commit"] = "HEAD~1"
    assert errors(card)


def test_series_must_be_null_in_m1(fixture_repo):
    assert errors(example_card(fixture_repo, series={"id": "x", "part": 1, "of": 2}))


def test_schema_document_wraps_cards(fixture_repo):
    doc = validator.card_schema(PERSONAS)
    assert doc["type"] == "object"
    assert doc["properties"]["cards"]["items"] == {"$ref": "#/$defs/card"}
