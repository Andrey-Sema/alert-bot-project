"""Alembic migration checks against the disposable PostgreSQL CI service."""

import asyncio
import os
import sys

import asyncpg
import pytest


async def _alembic(*arguments: str) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, output.decode(errors="replace")


@pytest.mark.asyncio
async def test_upgrade_adopts_legacy_schema_and_protects_data_api() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        pytest.skip("disposable PostgreSQL service runs in CI")

    connection = await asyncpg.connect(host="127.0.0.1", user="postgres", password="postgres", database="postgres")
    try:
        await connection.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') "
            "THEN CREATE ROLE anon NOLOGIN; END IF; "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') "
            "THEN CREATE ROLE authenticated NOLOGIN; END IF; END $$"
        )
        await connection.execute("CREATE TABLE user_settings (user_id BIGINT PRIMARY KEY)")
        await connection.execute(
            "CREATE TABLE user_triggers (user_id BIGINT REFERENCES user_settings(user_id) ON DELETE CASCADE, "
            "trigger_word VARCHAR(50), PRIMARY KEY (user_id, trigger_word))"
        )
        await connection.execute("INSERT INTO user_settings (user_id) VALUES (123)")
        await connection.execute("INSERT INTO user_triggers (user_id, trigger_word) VALUES (123, 'center')")
        await connection.execute("GRANT ALL ON user_settings, user_triggers TO anon, authenticated")

        await _alembic("upgrade", "head")
        assert await connection.fetchval("SELECT count(*) FROM user_settings WHERE user_id = 123") == 1
        assert await connection.fetchval("SELECT count(*) FROM user_triggers WHERE trigger_word = 'center'") == 1
        for table in ("user_settings", "user_triggers"):
            assert await connection.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid = $1::regclass", table)
            assert not await connection.fetchval("SELECT has_table_privilege('anon', $1, 'SELECT')", table)
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE indexname IN "
                "('ix_user_settings_potvory_gin', 'ix_user_settings_muted_until', 'ix_user_triggers_word_user')"
            )
            == 3
        )

        await _alembic("downgrade", "base")
        await connection.execute("DROP TABLE user_triggers, user_settings CASCADE")
        await _alembic("upgrade", "head")
        assert await connection.fetchval("SELECT count(*) FROM user_settings") == 0
        assert await connection.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE oid = 'user_activity_daily'::regclass"
        )
        await connection.execute("INSERT INTO user_settings (user_id) VALUES (456)")
        await connection.execute(
            "INSERT INTO user_activity_daily (user_id, activity_date, interacted) VALUES (456, CURRENT_DATE, true)"
        )
        await connection.execute("DELETE FROM user_settings WHERE user_id = 456")
        assert await connection.fetchval("SELECT count(*) FROM user_activity_daily WHERE user_id = 456") == 0
        await _alembic("upgrade", "head")
    finally:
        await connection.close()
