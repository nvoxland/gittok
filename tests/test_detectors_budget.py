"""The regex time limit is per file and rule, not per line."""

import time
from types import SimpleNamespace

from gittok import detectors
from gittok.profiles import Detector


class SlowRx:
    def __init__(self):
        self.calls = 0

    def search(self, line, timeout=None):
        self.calls += 1
        time.sleep(0.03)
        return None


def test_budget_is_spent_across_lines(monkeypatch):
    monkeypatch.setattr(detectors, "REGEX_TIMEOUT_S", 0.1)
    d = Detector(id="r", tag="t", paths=("**",), weight=1.0, regex="x")
    sf = SimpleNamespace(path="a.py", lines=["x"] * 100)
    rx = SlowRx()
    stats: dict = {}
    t = time.monotonic()
    out = detectors._regex_hits(d, rx, sf, stats)
    assert out == []
    assert time.monotonic() - t < 0.5
    assert rx.calls < 20
    assert stats["timed_out"] == [{"rule_id": "r", "path": "a.py"}]
