"""Fixtures for the active FastAPI regression suite.

The auth module reads SESSION_SECRET at import time and the manager resolves its
database path from AWI_AUTH_DB. Set both before importing the application so
tests never read or write the developer's runtime signing key or database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    monkeypatch.setenv("SESSION_SECRET", "awi-regression-tests-only-secret-32-bytes")
    monkeypatch.setenv("AWI_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("AWI_ADMIN_BOOTSTRAP_PASSWORD", raising=False)

    from backend.core import local_auth
    from backend.core.auth_session import AWIRole
    from backend.api.main import create_app

    # A cached manager could otherwise keep a previous test's database open.
    local_auth._auth_manager = None
    app = create_app()
    manager = local_auth.LocalAuthManager()
    local_auth._auth_manager = manager
    admin = manager.create_user(
        username="regression-admin",
        display_name="Regression Admin",
        email="regression-admin@example.invalid",
        role=AWIRole.SYSTEM_ADMIN,
        initial_password="Regression!2026",
        must_change_pw=False,
    )
    access_token, access_jti = local_auth.create_access_token(
        admin.user_id, admin.username, admin.role.value, must_change_pw=False
    )
    manager._persist_token(access_jti, admin.user_id, "access", 480, None, None)

    with TestClient(app) as client:
        yield {
            "client": client,
            "manager": manager,
            "admin": admin,
            "admin_token": access_token,
            "auth": local_auth,
            "roles": AWIRole,
        }
    local_auth._auth_manager = None


@pytest.fixture
def admin_headers(api_client: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_client['admin_token']}"}
