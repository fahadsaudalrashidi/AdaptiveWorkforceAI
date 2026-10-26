"""Small storage boundary for the existing authentication SQL.

SQLite remains the development default. PostgreSQL is explicitly selected in
production, never silently replaced by local storage on a connection failure.
Only fixed internal SQL is adapted; user values remain driver-bound parameters.
"""
from __future__ import annotations

import os
import re
import sqlite3


def auth_backend() -> str:
    backend = os.environ.get("AWI_AUTH_BACKEND", "sqlite").strip().lower()
    if backend not in {"sqlite", "postgres"}:
        raise RuntimeError("AWI_AUTH_BACKEND must be sqlite or postgres.")
    return backend


def _postgres_sql(statement: str) -> str:
    if re.match(r"\s*(CREATE|ALTER|DROP|PRAGMA)\b", statement, re.I):
        raise RuntimeError("Production authentication schema is managed by Publish, not application startup.")
    statement = re.sub(
        r"\busername\s*=\s*\?\s+COLLATE\s+NOCASE",
        "LOWER(username)=LOWER(?)", statement, flags=re.I,
    )
    if "INSERT OR REPLACE INTO awi_account_locks" in statement:
        statement = statement.replace("INSERT OR REPLACE", "INSERT")
        statement += (
            " ON CONFLICT (LOWER(username)) DO UPDATE SET "
            "locked_at=EXCLUDED.locked_at, locked_until=EXCLUDED.locked_until, reason=EXCLUDED.reason"
        )
    if "INSERT OR IGNORE INTO awi_active_tokens" in statement:
        statement = statement.replace("INSERT OR IGNORE", "INSERT")
        statement += " ON CONFLICT (jti) DO NOTHING"
    # SQL literals here never contain ?, only the application's placeholders.
    return statement.replace("?", "%s")


class PostgresAuthConnection:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def execute(self, statement, parameters=()):
        import psycopg
        try:
            return self.connection.execute(_postgres_sql(statement), parameters)
        except psycopg.IntegrityError:
            # Preserve the existing public duplicate-user error handling without
            # exposing server diagnostics or connection credentials.
            raise sqlite3.IntegrityError("Duplicate or invalid authentication record.") from None

    def commit(self):
        return self.connection.commit()


def connect_postgres() -> PostgresAuthConnection:
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("PostgreSQL authentication requires DATABASE_URL.")
    try:
        connection = psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    except psycopg.Error:
        raise RuntimeError("The authentication database is unavailable.") from None
    return PostgresAuthConnection(connection)


def verify_postgres_schema() -> None:
    import psycopg
    # Read-only readiness checks. Managed production DDL is applied by Publish.
    tables = {
        "awi_local_users": "user_id, username, display_name, email, role, password_hash, is_active, must_change_pw, created_at, last_login",
        "awi_login_attempts": "id, username, attempted_at, success, ip_address, user_agent",
        "awi_account_locks": "username, locked_at, locked_until, reason",
        "awi_active_tokens": "jti, user_id, token_type, issued_at, expires_at, revoked, ip_address, user_agent",
        "awi_security_audit": "id, event_type, username, user_id, ip_address, user_agent, detail, occurred_at",
    }
    try:
        with connect_postgres() as connection:
            for table, columns in tables.items():
                connection.execute(f"SELECT {columns} FROM {table} LIMIT 0")
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
        raise RuntimeError("Authentication schema is not ready. Apply the development schema and publish its database changes.") from None
