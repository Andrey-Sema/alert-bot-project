# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
from unittest.mock import AsyncMock, MagicMock

import pytest

from alert_bot_project.bot.middlewares.throttling import ThrottlingMiddleware


@pytest.mark.asyncio
class TestThrottlingMiddleware:
    async def test_passthrough_when_no_event_user(self) -> None:
        mock_redis = AsyncMock()
        middleware = ThrottlingMiddleware(mock_redis)
        mock_handler = AsyncMock(return_value="handled")

        result = await middleware(mock_handler, MagicMock(), {})

        assert result == "handled"
        mock_handler.assert_called_once()
        mock_redis.set.assert_not_called()

    async def test_allows_first_update_and_calls_handler(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.set.return_value = True
        middleware = ThrottlingMiddleware(mock_redis, rate_limit=0.5)
        mock_handler = AsyncMock(return_value="handled")
        mock_user = MagicMock(id=42)

        result = await middleware(mock_handler, MagicMock(), {"event_from_user": mock_user})

        assert result == "handled"
        mock_handler.assert_called_once()
        mock_redis.set.assert_called_once_with("throttle:42", "1", nx=True, px=500)

    async def test_throttles_rapid_repeat_update(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.set.return_value = None  # NX-ключ вже існує — недавній апдейт від цього юзера
        middleware = ThrottlingMiddleware(mock_redis)
        mock_handler = AsyncMock(return_value="handled")
        mock_user = MagicMock(id=42)

        result = await middleware(mock_handler, MagicMock(), {"event_from_user": mock_user})

        assert result is None
        mock_handler.assert_not_called()
