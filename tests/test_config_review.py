"""Review fixes: settings values are checked (type and range), models merge deep, null keys."""

from pathlib import Path

import pytest

from gittok import overlay
from gittok.config import ConfigError, load_config


def settings(root: Path, text: str, local: str = "") -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "settings.yaml").write_text(text)
    if local:
        (root / "local").mkdir(exist_ok=True)
        (root / "local" / "settings.yaml").write_text(local)


@pytest.mark.parametrize("local", [
    "agent:\n  min_burn_per_day: 0\n",
    "agent:\n  packet_size: 0\n",
    "agent:\n  packet_size: 6\n",
    "agent:\n  per_day_runs: ten\n",
    "agent:\n  target_runway_days: '3'\n",
    "agent:\n  max_count: true\n",
    "agent:\n  intro_share: 1.5\n",
    "agent:\n  wake_cooldown_hours: -1\n",
    "analysis:\n  churn_windows_days: 30\n",
    "analysis:\n  churn_windows_days: [30, x]\n",
    "analysis:\n  churn_windows_days: [0]\n",
    "server:\n  port: 0\n",
    "server:\n  port: '80'\n",
    "server:\n  host: 5\n",
    "render:\n  image_width: 0\n",
    "gc:\n  interval_s: 0\n",
    "research:\n  max_read_lines: 0\n",
])
def test_a_bad_number_is_a_one_line_config_error(tmp_path, local):
    settings(tmp_path, "{}\n", local)
    with pytest.raises(ConfigError) as e:
        load_config(tmp_path)
    assert "\n" not in str(e.value) and "settings.yaml" in str(e.value)


def test_check_reports_a_bad_number_instead_of_a_traceback(tmp_path):
    settings(tmp_path, "{}\n", "analysis:\n  churn_windows_days: 30\n")
    out = overlay.check(tmp_path, tmp_path)
    assert not out["ok"] and any("churn_windows_days" in e for e in out["errors"])


def test_good_numbers_still_load(tmp_path):
    settings(tmp_path, "{}\n", "agent:\n  packet_size: 5\n  intro_share: 0\n"
                               "analysis:\n  churn_windows_days: [7, 14]\nserver:\n  port: 8000\n")
    cfg = load_config(tmp_path)
    assert cfg.settings.agent.packet_size == 5
    assert cfg.settings.analysis.churn_windows_days == (7, 14)


def test_a_local_codex_model_keeps_the_shipped_claude_tiers(tmp_path):
    shipped = "agent:\n  models:\n    claude: {light: haiku, standard: sonnet}\n    codex: {}\n"
    settings(tmp_path, shipped, "agent:\n  models:\n    codex: {light: gpt-mini}\n")
    models = load_config(tmp_path).settings.agent.models
    assert models["claude"] == {"light": "haiku", "standard": "sonnet"}
    assert models["codex"] == {"light": "gpt-mini"}
    settings(tmp_path, shipped, "agent:\n  models:\n    claude: {light: opus}\n")
    models = load_config(tmp_path).settings.agent.models
    assert models["claude"] == {"light": "opus", "standard": "sonnet"}


def test_overlay_get_shows_the_same_deep_merge(tmp_path):
    shipped = "agent:\n  models:\n    claude: {light: haiku, standard: sonnet}\n    codex: {}\n"
    settings(tmp_path, shipped, "agent:\n  models:\n    codex: {light: gpt-mini}\n")
    eff = overlay.get(tmp_path, tmp_path, "settings", "agent.models")["effective"]
    assert eff["claude"]["standard"] == "sonnet" and eff["codex"] == {"light": "gpt-mini"}


@pytest.mark.parametrize("claude", [
    "{light: fast}", "{light: gpt-5}", "{standard: 'sonnet '}", "{light: 5}", "{light: [a]}",
])
def test_a_claude_tier_must_be_a_claude_model(tmp_path, claude):
    settings(tmp_path, "{}\n", f"agent:\n  models:\n    claude: {claude}\n")
    with pytest.raises(ConfigError, match="models.claude"):
        load_config(tmp_path)


@pytest.mark.parametrize("value", ["haiku", "sonnet", "opus", "inherit", "claude-sonnet-4-5",
                                   "''", "null"])
def test_a_claude_tier_takes_an_alias_a_full_id_or_nothing(tmp_path, value):
    settings(tmp_path, "{}\n", f"agent:\n  models:\n    claude: {{light: {value}}}\n")
    load_config(tmp_path)


@pytest.mark.parametrize("models", ["0", "[]", "''", "[a]"])
def test_models_must_be_a_mapping(tmp_path, models):
    settings(tmp_path, "{}\n", f"agent:\n  models: {models}\n")
    with pytest.raises(ConfigError, match="models"):
        load_config(tmp_path)


@pytest.mark.parametrize("tiers", ["0", "[]", "''"])
def test_a_harness_entry_must_be_a_mapping(tmp_path, tiers):
    settings(tmp_path, "{}\n", f"agent:\n  models:\n    codex: {tiers}\n")
    with pytest.raises(ConfigError, match="models.codex"):
        load_config(tmp_path)


def test_a_null_data_dir_means_the_default(tmp_path):
    settings(tmp_path, "{}\n", "data_dir:\n")
    assert load_config(tmp_path).settings.data_dir == (tmp_path / "data").resolve()
    settings(tmp_path, "data_dir:\n", "")
    assert load_config(tmp_path).settings.data_dir == (tmp_path / "data").resolve()
