"""Pairing by code. A device that is not paired asks for a short code; the user tells Claude
the code, and Claude approves it with the `pair_device` tool (or `gittok pair <code>`). The
device polls with its secret request id and, once approved, gets the pairing cookie.

The feed server and the MCP process are separate processes, so the requests live in the
database. Only a code that the user typed approves a request: a device on the network can
make requests, but it cannot approve one.
"""

import re
import secrets
from datetime import datetime, timedelta

from . import db

# No characters that look alike (0/O, 1/I/L).
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_TTL = timedelta(minutes=10)
MAX_PENDING = 20
CODE_RE = re.compile(rf"[{ALPHABET}]{{4}}-[{ALPHABET}]{{2}}")

NO_SUCH_CODE = (
    "No device shows this code now (codes last 10 minutes and work once). Ask the user to "
    "open GitTok on the device, tap 'Pair with a code', and say the code that it shows."
)


class TooManyRequests(Exception):
    pass


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _prune(conn, now: datetime) -> None:
    conn.execute("DELETE FROM pair_requests WHERE created_at <= ?", (_iso(now - CODE_TTL),))


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(6))
    return f"{raw[:4]}-{raw[4:]}"


def normalize(typed: str) -> str:
    """The code as stored, from what a person typed: case, spaces and dashes do not count."""
    raw = re.sub(r"[^0-9A-Za-z]", "", typed or "").upper()
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 6 else raw


def request(conn, now: datetime) -> dict:
    """A new request: {id (secret, for the device only), code (for the user to say)}."""
    with db.immediate(conn):
        _prune(conn, now)
        n = conn.execute("SELECT COUNT(*) FROM pair_requests").fetchone()[0]
        if n >= MAX_PENDING:
            raise TooManyRequests("too many devices wait for a pairing code; try again later")
        while True:
            code = _new_code()
            if not conn.execute("SELECT 1 FROM pair_requests WHERE code = ?", (code,)).fetchone():
                break
        rid = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO pair_requests(id, code, created_at) VALUES (?, ?, ?)",
            (rid, code, _iso(now)),
        )
    return {"id": rid, "code": code}


def approve(conn, typed: str, now: datetime) -> dict:
    """Approve the waiting request with this code. {ok, message}."""
    code = normalize(typed)
    with db.immediate(conn):
        _prune(conn, now)
        cur = conn.execute(
            "UPDATE pair_requests SET approved_at = ? WHERE code = ? AND approved_at IS NULL",
            (_iso(now), code),
        )
    if cur.rowcount != 1:
        return {"ok": False, "code": code, "message": NO_SUCH_CODE}
    return {
        "ok": True,
        "code": code,
        "message": "Approved. The device opens the feed within a few seconds.",
    }


def status(conn, request_id: str, now: datetime) -> dict:
    """{state: pending|approved|unknown, code?}. An approved request is used up here: the
    caller sets the pairing cookie, and a second look finds nothing."""
    with db.immediate(conn):
        _prune(conn, now)
        row = conn.execute(
            "SELECT code, approved_at FROM pair_requests WHERE id = ?", (request_id or "",)
        ).fetchone()
        if row is None:
            return {"state": "unknown"}
        if row["approved_at"] is None:
            return {"state": "pending", "code": row["code"]}
        conn.execute("DELETE FROM pair_requests WHERE id = ?", (request_id,))
    return {"state": "approved"}
