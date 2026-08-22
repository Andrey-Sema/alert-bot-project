# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
from alert_bot_project.core_shared.config import config
from alert_bot_project.database.engine import engine


class TestEngineConfiguration:
    def test_pool_size_is_sourced_from_config(self) -> None:
        """DB_POOL_SIZE/DB_MAX_OVERFLOW з env.example мають реально доходити до движка,
        а не залишатись задокументованими, але мертвими налаштуваннями."""
        assert engine.pool.size() == config.DB_POOL_SIZE

    def test_pool_pre_ping_enabled(self) -> None:
        assert engine.pool._pre_ping is True
