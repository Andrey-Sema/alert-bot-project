from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alert_bot_project.core_shared.constants import MAX_GLOBAL_CUSTOM_TRIGGERS
from alert_bot_project.worker.custom_matcher import CustomTriggerMatcher


@pytest.mark.asyncio
async def test_matcher_rebuilds_only_when_version_changes() -> None:
    redis = AsyncMock()
    redis.get.side_effect = ["1", "1", "2"]
    redis.smembers.side_effect = [{"центр"}, {"пересип"}]
    matcher = CustomTriggerMatcher()
    assert await matcher.get_matches("центр", redis) == ["центр"]
    assert await matcher.get_matches("центр", redis) == ["центр"]
    assert await matcher.get_matches("пересип", redis) == ["пересип"]
    assert redis.smembers.await_count == 2


@settings(max_examples=60)
@given(
    phrase=st.text(alphabet="абвгдежзийклмнопрстуфхцчшщыэюя", min_size=3, max_size=20),
    suffix=st.text(alphabet="абвгдежзийклмнопрстуфхцчшщыэюя", min_size=0, max_size=4),
)
def test_custom_phrase_boundary_and_suffix(phrase: str, suffix: str) -> None:
    matcher = CustomTriggerMatcher()
    matcher._build({phrase})
    assert (phrase in matcher._match(f"!{phrase}{suffix}!")) is (len(suffix) <= 3)
    assert matcher._match(f"z{phrase}{suffix}!") == []


@pytest.mark.asyncio
async def test_matcher_rejects_unbounded_global_dictionary() -> None:
    redis = AsyncMock()
    redis.get.return_value = "1"
    redis.smembers.return_value = {f"phrase_{i}" for i in range(MAX_GLOBAL_CUSTOM_TRIGGERS + 1)}
    with pytest.raises(ValueError, match="limit exceeded"):
        await CustomTriggerMatcher().get_matches("test", redis)
