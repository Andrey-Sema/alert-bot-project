from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from alert_bot_project.core_shared.config import config

# Production-grade async engine configuration targeting Supabase instance
# ✅ СЕНЬОР-ФИКС: Полностью отключен кэш подготовленных выражений для совместимости с Supavisor (порт 6543)
engine = create_async_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
    connect_args={
        "timeout": 5,
        "command_timeout": 10,
        "ssl": "require",
        "statement_cache_size": 0,           # Каноничное отключение кэша стейтментов для asyncpg
        "prepared_statement_cache_size": 0   # Дополнительный оверрайд контроля кэша
    }
)

# Shared factory generating isolated state transaction parameters
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)