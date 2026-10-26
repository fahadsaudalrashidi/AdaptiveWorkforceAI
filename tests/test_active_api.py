"""Focused regression checks for the active, authenticated FastAPI routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("endpoint", "fixture_name", "result_key"),
    [
        (
            "/api/local/financial-intelligence",
            "financial_transactions_test_data.csv",
            "financial_intelligence",
        ),
        (
            "/api/local/accounting-intelligence",
            "accounting_gl_test_data.csv",
            "accounting_intelligence",
        ),
        (
            "/api/local/inventory-intelligence",
            "inventory_snapshot_only_test_data.csv",
            "inventory_intelligence",
        ),
        (
            "/api/local/contract-expiry",
            "contract_expiry_test_data.csv",
            "contract_expiry",
        ),
        (
            "/api/local/gosi-calculator",
            "gosi_calculator_test_data.csv",
            "gosi",
        ),
    ],
)
def test_csv_analysis_routes_accept_repository_fixtures(
    api_client: dict,
    admin_headers: dict[str, str],
    endpoint: str,
    fixture_name: str,
    result_key: str,
) -> None:
    fixture = ROOT / fixture_name
    assert fixture.is_file(), f"Missing repository CSV fixture: {fixture_name}"
    response = api_client["client"].post(
        endpoint,
        headers=admin_headers,
        files={"file": (fixture.name, fixture.read_bytes(), "text/csv")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert result_key in payload
    assert isinstance(payload[result_key], dict)
    assert payload["filename"] == fixture.name


def test_empty_upload_returns_a_structured_client_error(
    api_client: dict, admin_headers: dict[str, str]
) -> None:
    response = api_client["client"].post(
        "/api/local/financial-intelligence",
        headers=admin_headers,
        files={"file": ("empty.csv", b"", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["blocking_reasons"] == ["Uploaded file is empty."]


def test_malformed_upload_does_not_crash_the_api(
    api_client: dict, admin_headers: dict[str, str]
) -> None:
    response = api_client["client"].post(
        "/api/local/financial-intelligence",
        headers=admin_headers,
        files={"file": ("malformed.csv", b"\x00\xff\x00", "text/csv")},
    )

    assert response.status_code < 500, response.text
    assert isinstance(response.json(), dict)


def test_ai_status_reports_unavailable_local_and_cloud_providers(
    api_client: dict, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from backend.api import local_analysis_routes

    monkeypatch.setattr(
        local_analysis_routes, "_ai_analyst_ollama_reachable", lambda: False
    )
    monkeypatch.setattr(
        local_analysis_routes,
        "_agentic_check_cloud_mode",
        lambda: SimpleNamespace(
            configured=False,
            valid=False,
            detail="Provider disabled for regression test.",
            masked_key="(not configured)",
            model="",
        ),
    )
    local_response = api_client["client"].get(
        "/api/local/ai-business-analyst/registry", headers=admin_headers
    )
    cloud_response = api_client["client"].get(
        "/api/local/ai-business-analyst/agentic/status", headers=admin_headers
    )

    assert local_response.status_code == 200
    assert local_response.json()["ollama_reachable"] is False
    assert isinstance(local_response.json()["registry"], list)
    assert cloud_response.status_code == 200
    assert cloud_response.json()["cloud_configured"] is False
    assert cloud_response.json()["cloud_valid"] is False
    assert cloud_response.json()["local_fallback_reachable"] is False
    assert cloud_response.json()["tools_available"] == []


def test_expired_and_tampered_access_tokens_are_rejected(api_client: dict) -> None:
    auth = api_client["auth"]
    admin = api_client["admin"]
    expired = auth.jwt.encode(
        {
            "sub": admin.user_id,
            "username": admin.username,
            "role": admin.role.value,
            "must_change_pw": False,
            "jti": "expired-test-token",
            "iat": int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
            "type": "access",
        },
        auth._JWT_SECRET,
        algorithm="HS256",
    )
    valid, _ = auth.create_access_token(
        admin.user_id, admin.username, admin.role.value, must_change_pw=False
    )
    tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")

    for token in (expired, tampered):
        response = api_client["client"].get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 401


def test_login_refresh_rotation_and_logout_revoke_tokens(api_client: dict) -> None:
    client = api_client["client"]
    manager = api_client["manager"]
    response = client.post(
        "/api/auth/login",
        json={"username": "regression-admin", "password": "Regression!2026"},
    )
    assert response.status_code == 200, response.text
    first_pair = response.json()

    refreshed = client.post(
        "/api/auth/refresh", json={"refresh_token": first_pair["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    second_pair = refreshed.json()
    assert second_pair["access_token"] != first_pair["access_token"]
    assert second_pair["refresh_token"] != first_pair["refresh_token"]
    refresh_jti = api_client["auth"].decode_token(second_pair["refresh_token"])["jti"]
    with api_client["auth"]._connect() as conn:
        stored_refresh = conn.execute(
            "SELECT expires_at FROM awi_active_tokens WHERE jti = ?", (refresh_jti,)
        ).fetchone()
    assert stored_refresh is not None
    remaining = datetime.fromisoformat(stored_refresh["expires_at"]) - datetime.now(
        timezone.utc
    )
    assert timedelta(days=29) < remaining <= timedelta(days=30)

    reused_refresh = client.post(
        "/api/auth/refresh", json={"refresh_token": first_pair["refresh_token"]}
    )
    assert reused_refresh.status_code == 401

    logged_out = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {second_pair['access_token']}"},
    )
    assert logged_out.status_code == 204
    after_logout = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {second_pair['access_token']}"},
    )
    assert after_logout.status_code == 401
    assert manager.is_token_revoked(
        api_client["auth"].decode_token(second_pair["access_token"])["jti"]
    )


def test_authentication_and_role_checks_are_enforced(api_client: dict) -> None:
    client = api_client["client"]
    manager = api_client["manager"]
    auditor = manager.create_user(
        username="regression-auditor",
        display_name="Regression Auditor",
        email="regression-auditor@example.invalid",
        role=api_client["roles"].AUDITOR,
        initial_password="AuditorTest!2026",
        must_change_pw=False,
    )
    auditor_token, auditor_jti = api_client["auth"].create_access_token(
        auditor.user_id, auditor.username, auditor.role.value, must_change_pw=False
    )
    manager._persist_token(auditor_jti, auditor.user_id, "access", 480, None, None)

    assert client.get("/api/auth/me").status_code == 401
    assert client.get(
        "/api/auth/users", headers={"Authorization": f"Bearer {auditor_token}"}
    ).status_code == 403
    assert client.get(
        "/api/local/ai-business-analyst/registry",
        headers={"Authorization": f"Bearer {auditor_token}"},
    ).status_code == 403
    assert client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {api_client['admin_token']}"},
    ).status_code == 200

