"""Release checks. Real PostgreSQL tests opt in with AWI_TEST_POSTGRES=1.

Integration fixtures use a new, disposable development schema, never public
accounts or a production connection. No database credentials are printed.
"""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from backend.core import auth_database as db


class StorageBoundaryTests(unittest.TestCase):
    def test_development_does_not_implicitly_switch_storage(self):
        with patch.dict(os.environ, {"AWI_AUTH_BACKEND": "sqlite"}):
            self.assertEqual(db.auth_backend(), "sqlite")
        with patch.dict(os.environ, {"AWI_AUTH_BACKEND": "typo"}):
            with self.assertRaises(RuntimeError):
                db.auth_backend()

    def test_bound_values_never_become_sql(self):
        connection = MagicMock()
        adapter = db.PostgresAuthConnection(connection)
        value = "name'; DROP TABLE awi_local_users; --"
        adapter.execute("SELECT * FROM awi_local_users WHERE username=? COLLATE NOCASE", (value,))
        connection.execute.assert_called_once_with(
            "SELECT * FROM awi_local_users WHERE LOWER(username)=LOWER(%s)", (value,),
        )

    def test_known_upserts_and_no_startup_ddl(self):
        token_sql = db._postgres_sql("INSERT OR IGNORE INTO awi_active_tokens (jti) VALUES (?)")
        self.assertIn("ON CONFLICT (jti) DO NOTHING", token_sql)
        lock_sql = db._postgres_sql("INSERT OR REPLACE INTO awi_account_locks (username) VALUES (?)")
        self.assertIn("ON CONFLICT (LOWER(username)) DO UPDATE", lock_sql)
        for statement in ["CREATE TABLE bad (id INT)", "ALTER TABLE bad ADD x INT", "PRAGMA foreign_keys=ON", "DROP TABLE bad"]:
            with self.assertRaises(RuntimeError):
                db._postgres_sql(statement)

    def test_schema_verification_only_reads(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch.object(db, "connect_postgres", return_value=connection):
            db.verify_postgres_schema()
        self.assertEqual(connection.execute.call_count, 5)
        self.assertTrue(all(call.args[0].startswith("SELECT ") for call in connection.execute.call_args_list))

    def test_missing_database_cannot_fall_back(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                db.connect_postgres()

    def test_production_cannot_use_ephemeral_authentication(self):
        from backend.api.production import create_app
        with patch.dict(os.environ, {"SESSION_SECRET": ""}):
            with self.assertRaisesRegex(RuntimeError, "SESSION_SECRET"):
                create_app()
        with patch.dict(os.environ, {"SESSION_SECRET": "test-only-key-with-more-than-32-characters", "AWI_AUTH_BACKEND": "sqlite"}):
            with self.assertRaisesRegex(RuntimeError, "postgres"):
                create_app()


@unittest.skipUnless(os.environ.get("AWI_TEST_POSTGRES") == "1", "Opt-in development PostgreSQL integration")
class PostgresReleaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from backend.core import local_auth

        self.auth = local_auth
        self.schema = "awi_release_test_" + uuid4().hex
        # DATABASE_URL is supplied by Replit; never copy or log its value.
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)

        def connect():
            return db.PostgresAuthConnection(psycopg.connect(
                os.environ["DATABASE_URL"], row_factory=dict_row,
                options=f"-c search_path={self.schema}", connect_timeout=10,
            ))
        self.connect = connect
        with connect().connection as connection:
            connection.execute((Path(__file__).parents[1] / "db" / "auth_schema.sql").read_text())
        patches = [
            patch.dict(os.environ, {
                "AWI_AUTH_BACKEND": "postgres",
                "SESSION_SECRET": "production-tests-only-signing-key-with-32-characters",
                "AWI_ADMIN_BOOTSTRAP_PASSWORD": "",
                "THRIVE_NEW_ADMIN_USERNAME": "",
                "THRIVE_NEW_ADMIN_PASSWORD": "",
            }),
            patch.object(db, "connect_postgres", connect),
            patch.object(local_auth, "connect_postgres", connect),
            patch.object(local_auth, "_auth_manager", None),
            patch.object(local_auth, "_JWT_SECRET", "production-tests-only-signing-key-with-32-characters"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.manager = local_auth.LocalAuthManager()

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def user(self, username="ReleaseAdmin", email="release@example.invalid"):
        return self.manager.create_user(
            username, "Release Test", email, self.auth.AWIRole.SYSTEM_ADMIN,
            "ReleaseTest!2026", must_change_pw=False,
        )

    def test_case_insensitive_unique_accounts(self):
        user = self.user()
        self.assertEqual(self.manager.get_user_by_username("releaseadmin").user_id, user.user_id)
        with self.assertRaises(ValueError):
            self.user("RELEASEADMIN", "different@example.invalid")
        with self.assertRaises(ValueError):
            self.user("different-user", "RELEASE@EXAMPLE.INVALID")
        self.assertEqual(len(self.manager.list_users()), 1)

    def test_sessions_survive_manager_restart_and_revoke(self):
        user = self.user()
        result = self.manager.login("RELEASEADMIN", "ReleaseTest!2026")
        self.assertTrue(result.success)
        restarted = self.auth.LocalAuthManager()
        found, error = restarted.verify_token_and_get_user(result.access_token)
        self.assertIsNone(error)
        self.assertEqual(found.user_id, user.user_id)
        refresh_jti = self.auth.decode_token(result.refresh_token)["jti"]
        self.assertFalse(restarted.is_token_revoked(refresh_jti))
        restarted.logout(self.auth.decode_token(result.access_token)["jti"], user.user_id)
        self.assertIsNone(self.manager.verify_token_and_get_user(result.access_token)[0])

    def test_case_insensitive_lockout_and_unlock(self):
        user = self.user()
        for attempt in range(5):
            self.manager.login("releaseadmin" if attempt % 2 else "RELEASEADMIN", "Wrong!2026")
        self.assertTrue(self.manager.login("ReleaseAdmin", "ReleaseTest!2026").account_locked)
        self.assertTrue(self.manager.unlock_account("RELEASEADMIN", user.user_id))
        self.assertTrue(self.manager.login("releaseadmin", "ReleaseTest!2026").success)
        self.assertGreater(len(self.manager.get_security_audit_log()), 0)

    def test_production_ui_api_and_local_csv_share_one_server(self):
        from fastapi.testclient import TestClient
        from backend.api.production import create_app
        self.user()
        with TestClient(create_app()) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("text/html", page.headers["content-type"])
            self.assertEqual(page.headers["cache-control"], "no-store")
            self.assertEqual(client.get("/dashboard/analysis").status_code, 200)
            self.assertEqual(client.get("/api/v1/status").status_code, 200)
            self.assertEqual(client.get("/api/missing").status_code, 404)
            self.assertEqual(client.get("/assets/missing.js").status_code, 404)
            self.assertEqual(client.get("/data/awi_auth.db").status_code, 404)
            self.assertEqual(client.get("/api/auth/me").status_code, 401)
            self.assertEqual(client.post("/api/local/ai-business-analyst/agentic").status_code, 401)
            login = client.post("/api/auth/login", json={"username": "releaseadmin", "password": "ReleaseTest!2026"})
            self.assertEqual(login.status_code, 200)
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            self.assertEqual(client.get("/api/auth/me", headers=headers).status_code, 200)
            response = client.post(
                "/api/local/ai-business-analyst/agentic", headers=headers,
                data={"question": "كم عقد منتهي؟", "cloud_mode": "false"},
                files={"files": ("contracts.csv", b"ContractID,ContractStatus\nC1,Expired\nC2,Active\n", "text/csv")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("contract_expired_count", response.text)

    def test_empty_database_without_bootstrap_fails_explicitly(self):
        from backend.api.production import create_app
        with self.assertRaisesRegex(RuntimeError, "active account"):
            create_app()

    def test_first_boot_creates_admin_once_and_requires_password_change(self):
        from backend.api.production import create_app
        with patch.dict(os.environ, {"AWI_ADMIN_BOOTSTRAP_PASSWORD": "FirstBoot!2026Test"}):
            create_app()
            create_app()
        self.assertEqual(len(self.manager.list_users()), 1)
        result = self.manager.login("admin", "FirstBoot!2026Test")
        self.assertTrue(result.success)
        self.assertTrue(result.must_change_pw)

    def test_owner_configured_admin_is_created_once_without_changing_existing_admin(self):
        from backend.api.production import create_app
        original = self.manager.bootstrap_admin("Original!2026Test")
        with patch.dict(os.environ, {
            "THRIVE_NEW_ADMIN_USERNAME": "release-admin",
            "THRIVE_NEW_ADMIN_PASSWORD": "Temporary!2026Test",
        }):
            create_app()
            create_app()
        created = self.manager.get_user_by_username("release-admin")
        self.assertEqual(created.role, self.auth.AWIRole.SYSTEM_ADMIN)
        self.assertTrue(created.must_change_pw)
        self.assertEqual(len(self.manager.list_users()), 2)
        self.assertTrue(self.manager.login(original.username, "Original!2026Test").success)
        self.assertTrue(self.manager.login("release-admin", "Temporary!2026Test").success)
        ok, _ = self.manager.change_password(created.user_id, "Temporary!2026Test", "Changed!2026Test")
        self.assertTrue(ok)
        with patch.dict(os.environ, {
            "THRIVE_NEW_ADMIN_USERNAME": "RELEASE-ADMIN",
            "THRIVE_NEW_ADMIN_PASSWORD": "Different!2026Test",
        }):
            create_app()
        self.assertTrue(self.manager.login("release-admin", "Changed!2026Test").success)
        self.assertFalse(self.manager.get_user_by_id(created.user_id).must_change_pw)

    def test_additional_admin_never_elevates_or_reactivates_existing_users(self):
        from backend.api.production import create_app
        user = self.manager.create_user(
            username="ordinary-user", display_name="Test", email="test@example.invalid",
            role=self.auth.AWIRole.EXECUTIVE, initial_password="Viewer!2026Test",
        )
        with patch.dict(os.environ, {
            "THRIVE_NEW_ADMIN_USERNAME": "ordinary-user",
            "THRIVE_NEW_ADMIN_PASSWORD": "Temporary!2026Test",
        }):
            with self.assertRaisesRegex(ValueError, "inactive or non-admin"):
                create_app()
        self.assertEqual(self.manager.get_user_by_id(user.user_id).role, self.auth.AWIRole.EXECUTIVE)
        admin = self.manager.provision_additional_admin("inactive-admin", "Temporary!2026Test")
        self.manager.deactivate_user(admin.user_id)
        with self.assertRaisesRegex(ValueError, "inactive or non-admin"):
            self.manager.provision_additional_admin("inactive-admin", "Temporary!2026Test")

    def test_additional_admin_requires_valid_password_and_safe_username(self):
        for username in ("../unsafe", "x", "user name"):
            with self.assertRaisesRegex(ValueError, "username"):
                self.manager.provision_additional_admin(username, "Temporary!2026Test")
        with self.assertRaisesRegex(ValueError, "Password policy"):
            self.manager.provision_additional_admin("new-admin", "weak")
        self.assertIsNone(self.manager.get_user_by_username("new-admin"))
        from backend.api.production import create_app
        with patch.dict(os.environ, {
            "THRIVE_NEW_ADMIN_USERNAME": "new-admin",
            "THRIVE_NEW_ADMIN_PASSWORD": "",
        }):
            with self.assertRaisesRegex(RuntimeError, "THRIVE_NEW_ADMIN_PASSWORD"):
                create_app()


if __name__ == "__main__":
    unittest.main()
