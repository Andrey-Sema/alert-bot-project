from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from alert_bot_project.core_shared.config import config

# Production-grade async engine configuration targeting Supabase instance
# ✅ УЛУЧШЕНИЕ: Добавлен строгий сетевой контроль (таймауты + принудительный SSL для облака)
engine = create_async_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
    connect_args={
        "timeout": 5,
        "command_timeout": 10,
        "ssl": "require"
    }
)

# Shared factory generating isolated state transaction parameters
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)