# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.exc import SQLAlchemyError

from alert_bot_project.bot.middlewares.db import DatabaseMiddleware


@pytest.mark.asyncio
class TestDatabaseMiddleware:

    async def test_middleware_successful_flow(self) -> None:
        """Проверяем, что при успешном прохождении хендлера сессия создается, коммитится и закрывается"""
        mock_session = AsyncMock()
        mock_session.is_active = True

        with patch("alert_bot_project.bot.middlewares.db.AsyncSessionLocal") as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_session

            middleware = DatabaseMiddleware()
            mock_handler = AsyncMock(return_value="success_payload")
            mock_event = MagicMock()
            mock_data = {}

            result = await middleware(mock_handler, mock_event, mock_data)

            assert result == "success_payload"
            assert "db_session" in mock_data
            assert mock_data["db_session"] == mock_session
            mock_handler.assert_called_once_with(mock_event, mock_data)
            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()

    async def test_middleware_rollback_on_sqlalchemy_error(self) -> None:
        """Проверяем, что при падении БД внутри хендлера происходит откат транзакции (rollback)"""
        mock_session = AsyncMock()
        mock_session.is_active = True

        with patch("alert_bot_project.bot.middlewares.db.AsyncSessionLocal") as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_session

            middleware = DatabaseMiddleware()
            mock_handler = AsyncMock(side_effect=SQLAlchemyError("Supabase connection timeout"))
            mock_event = MagicMock()
            mock_data = {}

            with pytest.raises(SQLAlchemyError):
                await middleware(mock_handler, mock_event, mock_data)

            mock_session.rollback.assert_called_once()
            mock_session.commit.assert_not_called()

    async def test_middleware_rollback_on_unexpected_exception(self) -> None:
        """Проверяем, что при любой непредвиденной ошибке логики транзакция сбрасывается"""
        mock_session = AsyncMock()
        mock_session.is_active = True

        with patch("alert_bot_project.bot.middlewares.db.AsyncSessionLocal") as mock_session_local:
            mock_session_local.return_value.__aenter__.return_value = mock_session

            middleware = DatabaseMiddleware()
            mock_handler = AsyncMock(side_effect=ValueError("Unexpected validation error"))
            mock_event = MagicMock()
            mock_data = {}

            with pytest.raises(ValueError):
                await middleware(mock_handler, mock_event, mock_data)

            mock_session.rollback.assert_called_once()
            mock_session.commit.assert_not_called()