"""Crash-safe local outbox for source posts awaiting Redis acceptance."""

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path


class ScraperOutbox:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    def _run(self, query: str, params: tuple[object, ...] = (), *, fetch: bool = False) -> list[tuple[int, int, str]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS pending_posts ("
                "chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, payload TEXT NOT NULL, "
                "PRIMARY KEY (chat_id, message_id))"
            )
            cursor = connection.execute(query, params)
            return cursor.fetchall() if fetch else []

    async def put(self, chat_id: int, message_id: int, payload: str) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._run,
                "INSERT OR IGNORE INTO pending_posts (chat_id, message_id, payload) VALUES (?, ?, ?)",
                (chat_id, message_id, payload),
            )

    async def pending(self, limit: int = 100) -> list[tuple[int, int, str]]:
        async with self._lock:
            return await asyncio.to_thread(
                self._run,
                "SELECT chat_id, message_id, payload FROM pending_posts ORDER BY rowid LIMIT ?",
                (limit,),
                fetch=True,
            )

    async def delete(self, chat_id: int, message_id: int) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._run,
                "DELETE FROM pending_posts WHERE chat_id = ? AND message_id = ?",
                (chat_id, message_id),
            )

    async def count(self) -> int:
        async with self._lock:
            rows = await asyncio.to_thread(self._run, "SELECT COUNT(*) FROM pending_posts", fetch=True)
            return int(rows[0][0])
