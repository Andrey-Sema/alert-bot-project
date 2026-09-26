"""Actual PostgreSQL permission denials on a separate disposable CI database."""

import asyncio
import os
import secrets
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alert_bot_project.database.privileges import verify_runtime_privileges
from tests.test_migrations_postgres import _alembic

POLICY = Path(__file__).resolve().parents[1] / "deploy/postgres_roles.sql"


@pytest.mark.asyncio
async def test_separate_runtime_roles_and_migration_owner() -> None:
    if os.getenv("GITHUB_ACTIONS") != "true" and os.getenv("LOCAL_DB_SECURITY_TEST") != "1":
        pytest.skip("disposable PostgreSQL CI service only")
    port = int(os.getenv("SECURITY_TEST_PG_PORT", "5432"))
    admin = await asyncpg.connect(
        host="127.0.0.1", port=port, user="postgres", password="postgres", database="postgres"
    )
    await admin.execute("CREATE DATABASE alert_bot_security_test")
    connection = await asyncpg.connect(
        host="127.0.0.1", port=port, user="postgres", password="postgres", database="alert_bot_security_test"
    )
    clients: list[asyncpg.Connection] = []
    try:
        env = dict(os.environ)
        env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+asyncpg://postgres:postgres@localhost:{port}/alert_bot_security_test"
        )
        await _alembic("upgrade", "head", env=env)
        await connection.execute(POLICY.read_text(encoding="utf-8"))
        await connection.execute(POLICY.read_text(encoding="utf-8"))  # idempotent grants/policies
        passwords = {}
        for role in ("alert_bot_worker", "alert_bot_ui", "alert_bot_migrator"):
            password = secrets.token_hex(32)
            passwords[role] = password
            # Fixed role names and generated hex; never a user-controlled SQL identifier/value.
            await connection.execute(f"ALTER ROLE {role} PASSWORD '{password}'")
            client = await asyncpg.connect(
                host="127.0.0.1", port=port, user=role, password=password, database="alert_bot_security_test"
            )
            clients.append(client)
        worker, ui, migrator = clients
        await ui.execute("INSERT INTO public.user_settings(user_id) VALUES(777)")
        await ui.execute("INSERT INTO public.user_triggers(user_id, trigger_word) VALUES(777, 'center')")
        assert await worker.fetchval("SELECT count(*) FROM public.user_settings") == 1
        await worker.execute(
            "INSERT INTO public.user_activity_daily(user_id, activity_date, delivered) VALUES(777, CURRENT_DATE, true)"
        )
        for sql in (
            "UPDATE public.user_settings SET muted_until = CURRENT_TIMESTAMP WHERE user_id = 777",
            "DELETE FROM public.user_settings WHERE user_id = 777",
            "INSERT INTO public.user_triggers(user_id, trigger_word) VALUES(777, 'port')",
            "TRUNCATE public.user_activity_daily",
            "DROP TABLE public.user_settings",
            "CREATE TABLE public.worker_escalation(id integer)",
            "SELECT * FROM public.alembic_version",
            "SET ROLE alert_bot_migrator",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await worker.execute(sql)
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await ui.execute("DROP TABLE public.user_triggers")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await ui.execute("SET ROLE alert_bot_migrator")
        await migrator.execute("CREATE TABLE public.future_private_table(id integer)")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await worker.fetch("SELECT * FROM public.future_private_table")
        env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+asyncpg://alert_bot_migrator:{passwords['alert_bot_migrator']}"
            f"@localhost:{port}/alert_bot_security_test"
        )
        await _alembic("current", env=env)

        for service, role in (("worker", "alert_bot_worker"), ("bot_ui", "alert_bot_ui")):
            engine = create_async_engine(
                f"postgresql+asyncpg://{role}:{passwords[role]}@localhost:{port}/alert_bot_security_test",
                connect_args={"ssl": False},
            )
            try:
                async with AsyncSession(engine) as session:
                    await verify_runtime_privileges(session, service)
                    wrong_service = "bot_ui" if service == "worker" else "worker"
                    with pytest.raises(RuntimeError, match="identity"):
                        await verify_runtime_privileges(session, wrong_service)
                # A column-only privilege cannot evade the startup guard.
                if service == "worker":
                    await connection.execute("GRANT UPDATE(muted_until) ON public.user_settings TO alert_bot_worker")
                    async with AsyncSession(engine) as session:
                        with pytest.raises(RuntimeError, match="column privileges"):
                            await verify_runtime_privileges(session, service)
                    await connection.execute("REVOKE UPDATE(muted_until) ON public.user_settings FROM alert_bot_worker")
                    await connection.execute("GRANT alert_bot_migrator TO alert_bot_worker")
                    async with AsyncSession(engine) as session:
                        with pytest.raises(RuntimeError, match="identity"):
                            await verify_runtime_privileges(session, service)
                    await connection.execute("REVOKE alert_bot_migrator FROM alert_bot_worker")
                    await connection.execute("ALTER TABLE public.user_settings DISABLE ROW LEVEL SECURITY")
                    async with AsyncSession(engine) as session:
                        with pytest.raises(RuntimeError, match="missing RLS"):
                            await verify_runtime_privileges(session, service)
                    await connection.execute("ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY")
            finally:
                await engine.dispose()

        # Independent UI and worker sessions preserve the existing FK privacy-delete contract.
        await asyncio.gather(
            worker.fetchval("SELECT count(*) FROM public.user_settings"),
            ui.fetchval("SELECT count(*) FROM public.user_settings"),
        )
        await ui.execute("DELETE FROM public.user_settings WHERE user_id = 777")
        assert await worker.fetchval("SELECT count(*) FROM public.user_activity_daily") == 0
        await connection.execute("ALTER ROLE alert_bot_worker CREATEROLE")
        with pytest.raises(asyncpg.RaiseError, match="Unsafe existing"):
            await connection.execute(POLICY.read_text(encoding="utf-8"))
        await connection.execute("ROLLBACK")
        await connection.execute("ALTER ROLE alert_bot_worker NOCREATEROLE")
    finally:
        await asyncio.gather(*(client.close() for client in clients))
        await connection.close()
        await admin.execute("DROP DATABASE alert_bot_security_test WITH (FORCE)")
        await admin.close()
