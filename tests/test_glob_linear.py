"""A glob that came as data cannot hang the matcher."""

import time

import pytest

from gittok import profiles


def test_many_stars_match_in_bounded_time():
    g = "*a" * 14 + "*b"
    m = profiles.glob_matcher(g)
    t = time.monotonic()
    assert not m("a" * 60)
    assert m("a" * 20 + "b")
    assert time.monotonic() - t < 1.0


def test_many_double_stars_and_slashes_in_bounded_time():
    m = profiles.glob_matcher("**/" * 12 + "x.py")
    t = time.monotonic()
    assert not m("a/" * 40 + "y.py")
    assert m("a/b/x.py")
    assert time.monotonic() - t < 1.0


def test_nfa_matches_like_the_simple_semantics():
    g = profiles.glob_matcher
    m = g("*a*b*c*d*e")  # more than two wildcards: the linear matcher
    assert m("xaxbxcxdxe") and m("dir/xaxbxcxdxe") and not m("xaxbxcxdx")
    assert not m("a/b/c/d/e")  # * does not cross "/"
    m = g("src/**/t*/*.p?/*[0-9]*")
    assert m("src/x/y/tz/a.py/x1y") and m("src/tz/a.pz/1")
    assert not m("src/tz/a.pz/xy")
    assert g("**/*a*b*c")("p/q/zazbzc")


def test_overlong_glob_is_rejected():
    with pytest.raises(ValueError):
        profiles.glob_matcher("a" * 1000)
