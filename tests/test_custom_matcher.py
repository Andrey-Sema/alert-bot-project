import time
import tracemalloc
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


def test_matcher_5000_phrase_latency_and_memory_budget() -> None:
    phrases = {f"сектор_{number:05d}" for number in range(MAX_GLOBAL_CUSTOM_TRIGGERS)}
    matcher = CustomTriggerMatcher()
    tracemalloc.start()
    try:
        started = time.perf_counter()
        matcher._build(phrases)
        build_seconds = time.perf_counter() - started
        samples = []
        for _ in range(100):
            started = time.perf_counter()
            assert matcher._match("Увага! Загроза у сектор_04999 біля центру.") == ["сектор_04999"]
            samples.append(time.perf_counter() - started)
        peak_bytes = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert build_seconds < 10
    assert sorted(samples)[94] < 0.1
    assert peak_bytes < 100 * 1024 * 1024
