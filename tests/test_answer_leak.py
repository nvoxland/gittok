"""No endpoint that returns card JSON may reveal a quiz answer before it is answered."""

from fastapi.testclient import TestClient

from gittok import api
from tests.cards import quiz_card
from tests.conftest import make_config
from tests.test_api import seed


def _assert_hidden(card):
    inter = card.get("interaction") or {}
    assert "answer_index" not in inter and "explanation" not in inter
    assert "answer_index" not in ((card.get("resolved") or {}).get("interaction") or {})


def test_repo_profile_hides_quiz_answers(fixture_repo, tmp_path):
    cfg = make_config(fixture_repo, tmp_path)
    (cid,) = seed(cfg, fixture_repo, [quiz_card(fixture_repo)])
    client = TestClient(api.create_app(lambda: cfg))
    cards = client.get("/api/repos/fixture").json()["cards"]
    assert [c["id"] for c in cards] == [cid]
    _assert_hidden(cards[0])
