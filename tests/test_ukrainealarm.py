# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from alert_bot_project.services.ukrainealarm import (
    OFFICIAL_ALARM_KEY,
    AlarmStatePoller,
    UkraineAlarmClient,
    UkraineAlarmError,
)


class TestUkraineAlarmClient:
    def test_raises_without_api_key(self) -> None:
        with pytest.raises(UkraineAlarmError):
            UkraineAlarmClient("")

    def test_accepts_valid_api_key(self) -> None:
        client = UkraineAlarmClient("real_key")
        assert client is not None

    def test_is_air_active_true_on_matching_type(self) -> None:
        alerts = [{"activeAlerts": [{"type": "AIR"}]}]
        assert UkraineAlarmClient.is_air_active(alerts) is True

    def test_is_air_active_false_on_empty(self) -> None:
        assert UkraineAlarmClient.is_air_active([]) is False

    def test_is_air_active_false_on_non_air_type(self) -> None:
        alerts = [{"activeAlerts": [{"type": "ARTILLERY"}]}]
        assert UkraineAlarmClient.is_air_active(alerts) is False


class TestAlarmStatePollerDisabled:
    """Ключова регресія: без UKRAINEALARM_API_KEY поллер має вимкнутись сам,
    а не валити весь процес воркера (AlarmStatePoller створюється в worker.main()
    без try/except навколо конструктора)."""

    @pytest.mark.asyncio
    async def test_init_does_not_raise_without_api_key(self) -> None:
        mock_redis = AsyncMock()
        poller = AlarmStatePoller(mock_redis, api_key="")
        assert poller.client is None

    @pytest.mark.asyncio
    async def test_run_returns_immediately_without_api_key(self) -> None:
        mock_redis = AsyncMock()
        poller = AlarmStatePoller(mock_redis, api_key="")
        shutdown_event = asyncio.Event()

        await asyncio.wait_for(poller.run(shutdown_event), timeout=1.0)

        mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_with_api_key_polls_until_shutdown(self) -> None:
        mock_redis = AsyncMock()
        poller = AlarmStatePoller(mock_redis, api_key="real_key", region_id="123", poll_interval=0.01)
        shutdown_event = asyncio.Event()

        with patch.object(poller, "_poll_once", new=AsyncMock(side_effect=lambda: shutdown_event.set())):
            await asyncio.wait_for(poller.run(shutdown_event), timeout=2.0)


class TestAlarmStatePollerFailsafe:
    @pytest.mark.asyncio
    async def test_maybe_failsafe_writes_configured_default(self) -> None:
        mock_redis = AsyncMock()
        poller = AlarmStatePoller(mock_redis, api_key="real_key", region_id="123", state_ttl=90)

        with patch("alert_bot_project.services.ukrainealarm.config") as mock_config:
            mock_config.OFFICIAL_ALARM_FAILSAFE = True
            await poller._maybe_failsafe()

        mock_redis.set.assert_called_once_with(OFFICIAL_ALARM_KEY, "1", ex=90)

    @pytest.mark.asyncio
    async def test_maybe_failsafe_skips_while_state_still_fresh(self) -> None:
        mock_redis = AsyncMock()
        poller = AlarmStatePoller(mock_redis, api_key="real_key", region_id="123", state_ttl=90)
        await poller._write_state(True)
        mock_redis.reset_mock()

        await poller._maybe_failsafe()

        mock_redis.set.assert_not_called()
