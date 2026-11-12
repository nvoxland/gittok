"""The LAN address lookup must not stall the server when the host name does not resolve."""

import time

from gittok import social


def _slow(seconds):
    def getaddrinfo(*args, **kwargs):
        time.sleep(seconds)
        return [(None, None, None, "", ("10.9.8.7", 0))]

    return getaddrinfo


def test_a_slow_host_name_lookup_does_not_stall(monkeypatch):
    social._host_addresses_reset()
    monkeypatch.setattr(social, "HOST_LOOKUP_WAIT", 0.2)
    monkeypatch.setattr(social.socket, "getaddrinfo", _slow(30.0))
    start = time.monotonic()
    addrs = social.lan_addresses()
    assert time.monotonic() - start < 10  # far under the 30 s of the lookup, even under load
    assert "10.9.8.7" not in addrs


def test_the_host_name_lookup_runs_once_for_many_calls(monkeypatch):
    social._host_addresses_reset()
    calls = []

    def getaddrinfo(*args, **kwargs):
        calls.append(1)
        return [(None, None, None, "", ("10.9.8.7", 0))]

    monkeypatch.setattr(social.socket, "getaddrinfo", getaddrinfo)
    for _ in range(5):
        assert "10.9.8.7" in social.lan_addresses()
    assert len(calls) == 1


def test_a_slow_lookup_is_not_started_again_while_it_runs(monkeypatch):
    social._host_addresses_reset()
    calls = []

    def getaddrinfo(*args, **kwargs):
        calls.append(1)
        time.sleep(30.0)
        return []

    monkeypatch.setattr(social, "HOST_LOOKUP_WAIT", 0.2)
    monkeypatch.setattr(social.socket, "getaddrinfo", getaddrinfo)
    social.lan_addresses()
    social.lan_addresses()
    assert len(calls) == 1
