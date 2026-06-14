import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from alert_bot_project.core_shared.config import config

# Production-grade async engine configuration targeting Supabase instance
# Relies on host-provided system certificates natively or direct standard connection topologies
engine = create_async_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,  # Probes standard connectivity status checks before executing calls
    pool_size=10,        # Default persistent base limits allocation sizes
    max_overflow=20,     # Spike connection boundaries ceiling limit configurations
    echo=False
)

# Shared factory generating isolated state transaction parameters
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False  # Crucial safety parameter handling long-lived asynchronous tasks
)


async def get_db_session() -> AsyncSession:
    """Asynchronous context lifecycle operational factory iterator dependency inject."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()