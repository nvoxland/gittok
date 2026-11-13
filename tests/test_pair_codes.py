"""Pairing by code: a device that is not paired asks for a short code, the user tells Claude
the code, and Claude approves it. The approval crosses processes through the database."""

from datetime import UTC, datetime, timedelta

import pytest

from gittok import db, pair_codes

T0 = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    with db.session(tmp_path / "gittok.db") as c:
        yield c


def test_a_request_gives_a_secret_id_and_a_short_code(conn):
    req = pair_codes.request(conn, T0)
    assert len(req["id"]) >= 32
    assert pair_codes.CODE_RE.fullmatch(req["code"])
    assert set(req["code"].replace("-", "")) <= set(pair_codes.ALPHABET)
    assert pair_codes.status(conn, req["id"], T0) == {"state": "pending", "code": req["code"]}


def test_codes_have_no_characters_that_look_alike():
    for c in "01OIL":
        assert c not in pair_codes.ALPHABET


def test_approve_by_code_then_status_is_approved_once(conn):
    req = pair_codes.request(conn, T0)
    out = pair_codes.approve(conn, req["code"], T0 + timedelta(minutes=1))
    assert out["ok"] is True
    assert pair_codes.status(conn, req["id"], T0)["state"] == "approved"
    # The approval is used up: a second look finds nothing.
    assert pair_codes.status(conn, req["id"], T0)["state"] == "unknown"


@pytest.mark.parametrize("typed", ["{c}", "{lower}", " {bare} ", "{spaced}"])
def test_approve_accepts_the_code_as_a_person_types_it(conn, typed):
    req = pair_codes.request(conn, T0)
    code = req["code"]
    given = typed.format(
        c=code, lower=code.lower(), bare=code.replace("-", ""), spaced=code.replace("-", " ")
    )
    assert pair_codes.approve(conn, given, T0)["ok"] is True


def test_an_unknown_code_is_not_approved_and_says_what_to_do(conn):
    pair_codes.request(conn, T0)
    out = pair_codes.approve(conn, "ZZZZ-ZZ", T0)
    assert out["ok"] is False
    assert "Pair with a code" in out["message"]


def test_a_code_expires(conn):
    req = pair_codes.request(conn, T0)
    late = T0 + pair_codes.CODE_TTL + timedelta(seconds=1)
    assert pair_codes.approve(conn, req["code"], late)["ok"] is False
    assert pair_codes.status(conn, req["id"], late)["state"] == "unknown"


def test_an_approval_that_was_not_picked_up_expires_too(conn):
    req = pair_codes.request(conn, T0)
    pair_codes.approve(conn, req["code"], T0)
    late = T0 + pair_codes.CODE_TTL + timedelta(seconds=1)
    assert pair_codes.status(conn, req["id"], late)["state"] == "unknown"


def test_the_number_of_waiting_codes_is_capped(conn):
    for _ in range(pair_codes.MAX_PENDING):
        pair_codes.request(conn, T0)
    with pytest.raises(pair_codes.TooManyRequests):
        pair_codes.request(conn, T0)
    # Old requests expire and make room again.
    pair_codes.request(conn, T0 + pair_codes.CODE_TTL + timedelta(seconds=1))


def test_status_of_an_id_that_was_never_made(conn):
    assert pair_codes.status(conn, "nope", T0)["state"] == "unknown"
    assert pair_codes.status(conn, "", T0)["state"] == "unknown"
