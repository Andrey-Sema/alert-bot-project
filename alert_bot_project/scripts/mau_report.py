"""Print anonymous 30-day activity counts from the configured PostgreSQL."""

import asyncio
from datetime import UTC, datetime

from alert_bot_project.database.activity import count_active_users
from alert_bot_project.database.engine import AsyncSessionLocal


async def main() -> None:
    async with AsyncSessionLocal() as session:
        interacted, delivered = await count_active_users(session)
    today = datetime.now(UTC).date()
    print(f"as_of_utc={today} interacted_mau_30d={interacted} delivered_users_30d={delivered}")


if __name__ == "__main__":
    asyncio.run(main())
