"""Reject privileged or mismatched database identities before service startup."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROLE_NAMES = {"worker": "alert_bot_worker", "bot_ui": "alert_bot_ui"}
TABLES = ("user_settings", "user_triggers", "user_activity_daily", "alembic_version")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def allowed_privileges(service: str, table: str) -> set[str]:
    if service not in ROLE_NAMES or table not in TABLES:
        raise ValueError("Unknown database service/table")
    if table == "alembic_version":
        return set()
    if service == "worker" and table != "user_activity_daily":
        return {"SELECT"}
    return {"SELECT", "INSERT", "UPDATE", "DELETE"}


async def verify_runtime_privileges(session: AsyncSession, service: str) -> None:
    expected = ROLE_NAMES.get(service)
    if expected is None:
        raise ValueError("Unknown runtime service")
    row = (
        (
            await session.execute(
                text("""
            SELECT current_user AS identity, session_user AS login, rolsuper OR rolcreatedb OR rolcreaterole OR
                   rolinherit OR rolreplication OR rolbypassrls AS unsafe,
                   EXISTS (SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid) AS memberships,
                   has_schema_privilege(current_user, 'public', 'CREATE') OR
                   has_database_privilege(current_user, current_database(), 'CREATE') AS ddl
            FROM pg_roles WHERE rolname = current_user
            """)
            )
        )
        .mappings()
        .one()
    )
    if row["identity"] != expected or row["login"] != expected or row["unsafe"] or row["memberships"] or row["ddl"]:
        raise RuntimeError("Unsafe or mismatched runtime database identity")
    states = (
        (
            await session.execute(
                text("""
            SELECT table_name, relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) AS owned,
                   relrowsecurity AS rls,
                   ARRAY[has_table_privilege(current_user, oid, 'SELECT'),
                         has_table_privilege(current_user, oid, 'INSERT'),
                         has_table_privilege(current_user, oid, 'UPDATE'),
                         has_table_privilege(current_user, oid, 'DELETE'),
                         has_table_privilege(current_user, oid, 'TRUNCATE'),
                         has_table_privilege(current_user, oid, 'REFERENCES'),
                         has_table_privilege(current_user, oid, 'TRIGGER')] AS granted,
                   ARRAY[has_any_column_privilege(current_user, oid, 'SELECT'),
                         has_any_column_privilege(current_user, oid, 'INSERT'),
                         has_any_column_privilege(current_user, oid, 'UPDATE'),
                         has_any_column_privilege(current_user, oid, 'REFERENCES')] AS columns,
                   ARRAY[has_table_privilege(current_user, oid, 'SELECT WITH GRANT OPTION'),
                         has_table_privilege(current_user, oid, 'INSERT WITH GRANT OPTION'),
                         has_table_privilege(current_user, oid, 'UPDATE WITH GRANT OPTION'),
                         has_table_privilege(current_user, oid, 'DELETE WITH GRANT OPTION')] AS grantable
            FROM unnest(CAST(:tables AS text[])) AS names(table_name)
            LEFT JOIN pg_class ON oid = to_regclass('public.' || table_name)
            """),
                {"tables": list(TABLES)},
            )
        )
        .mappings()
        .all()
    )
    for state in states:
        table = state["table_name"]
        if state["owned"] is None or state["owned"] or (table != "alembic_version" and not state["rls"]):
            raise RuntimeError("Unsafe runtime table ownership or missing RLS")
        allowed = allowed_privileges(service, table)
        if any(
            bool(granted) != (privilege in allowed)
            for privilege, granted in zip(PRIVILEGES, state["granted"], strict=True)
        ):
            raise RuntimeError("Runtime database privilege contract mismatch")
        if any(state["grantable"]):
            raise RuntimeError("Runtime must not delegate database privileges")
        for privilege, granted in zip(("SELECT", "INSERT", "UPDATE", "REFERENCES"), state["columns"], strict=True):
            if granted and privilege not in allowed:
                raise RuntimeError("Unexpected runtime column privileges")
