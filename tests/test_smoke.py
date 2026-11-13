import gittok


def test_import_version():
    """The two places that hold the version agree (the release workflow checks the tag too)."""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    assert gittok.__version__ == tomllib.loads(pyproject.read_text())["project"]["version"]
