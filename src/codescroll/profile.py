"""The plain-English profile file (SPEC §15): `<data_dir>/profile.md`, rewritten daily."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codescroll import db, steering

log = logging.getLogger(__name__)

MAX_AGE_S = 24 * 3600
CHECK_INTERVAL_S = 600.0
GAPS_SHOWN = 10


def profile_path(cfg) -> Path:
    return cfg.settings.data_dir / "profile.md"


def _rule_line(r: dict) -> str:
    detail = {
        "boost": f" x{r['factor']}",
        "prefer": f" x{r['factor']}",
        "focus": f" slots={r['slots']}",
        "limit": f" max={r['max_share']}",
    }.get(r["type"], "")
    until = f" until {r['expires_at']}" if r["expires_at"] else ""
    why = f' ("{r["reason"]}")' if r["reason"] else ""
    return f"- {r['type']} {r['feature']}={r['value']}{detail}{until}{why}"


def _claim_line(label: str, feature: str, c: dict) -> str:
    return f"- {feature}: {c['value']} ({label}, mean {c['mean']:.2f} over {c['n']:.0f} views)"


def render_profile(conn, cfg, now: datetime) -> str:
    p = steering.get_profile(conn, cfg, now=now)
    out = ["# CodeScroll profile", "", f"Updated: {now.strftime('%Y-%m-%d')}", ""]
    out += ["## What you like", ""] + [f"- {s}" for s in p["summary"]] + [""]
    if p["top"]:
        out += ["## Best and weakest", ""]
        for feature, c in sorted(p["top"].items()):
            out.append(_claim_line("best", feature, c))
            out.append(_claim_line("weakest", feature, p["bottom"][feature]))
        out.append("")
    out += ["## Active rules", ""]
    out += [_rule_line(r) for r in p["rules"]] or ["No active rules."]
    out += ["", "## Coverage gaps", ""]
    gaps = steering.coverage(conn, cfg)[:GAPS_SHOWN]
    out += [
        f"- {g['repo']}/{g['dir']}: {g['impressions']} views, {g['cards']} cards" for g in gaps
    ] or ["No repos configured."]
    return "\n".join(out) + "\n"


def write_profile(conn, cfg, now: datetime | None = None) -> Path:
    """Write the profile file atomically and return its path."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    path = profile_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render_profile(conn, cfg, now), encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_if_stale(
    cfg, max_age_s: float = MAX_AGE_S, clock: Callable[[], float] = time.time
) -> bool:
    """Write the profile when the file is missing or older than `max_age_s`."""
    path = profile_path(cfg)
    if path.is_file() and clock() - path.stat().st_mtime < max_age_s:
        return False
    with closing(db.open_db(cfg.settings.data_dir / "codescroll.db")) as conn:
        write_profile(conn, cfg)
    return True


class ProfileWorker:
    """Background thread: every `interval_s` (10 minutes) rewrite the profile if it is stale."""

    def __init__(
        self,
        get_config: Callable[[], Any],
        interval_s: float = CHECK_INTERVAL_S,
        max_age_s: float = MAX_AGE_S,
    ):
        self._get_config = get_config
        self._interval = interval_s
        self._max_age = max_age_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="profile-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                write_if_stale(self._get_config(), self._max_age)
            except Exception:
                log.exception("profile write failed")
            self._stop.wait(self._interval)
