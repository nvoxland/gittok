"""Review fixes: reward.yaml values are range-checked (the learner divides by some)."""

import pytest

from gittok import overlay
from gittok.config import ConfigError
from tests.test_overlay import local


@pytest.mark.parametrize("text", [
    "expected_ms_max: 0\n",
    "format_base_ms: {default: 0}\n",
    "format_base_ms: {meme: -5}\n",
    "like_weight: -1\n",
    "dislike_weight: -4\n",
    "ms_per_word: -1\n",
    "skip_ms: -1\n",
    "like_floor: 1.5\n",
    "weights: {$remove: [like]}\n",
    "weights: {$remove: [dwell]}\n",
    "slotting: {repeat_days: -1}\n",
    "slotting: {max_srs_per_batch: lots}\n",
    "slotting: {$remove: [max_srs_per_batch]}\n",
])
def test_a_reward_value_out_of_range_is_a_one_line_error(text, tmp_path):
    local(tmp_path, "reward.yaml", text)
    with pytest.raises(ConfigError) as e:
        overlay.load("reward", home=tmp_path)
    assert "\n" not in str(e.value) and "reward.yaml" in str(e.value)
