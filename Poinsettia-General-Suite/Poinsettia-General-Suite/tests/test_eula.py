import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import main


class EulaConsentRegressionTests(unittest.TestCase):
    """Regression coverage for version-aware EULA access control."""

    @classmethod
    def setUpClass(cls):
        cls.database = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        cls.database.close()
        cls.db_path = cls.database.name
        cls.app = main.app
        cls.app.config.update(TESTING=True, SECRET_KEY="test-session-secret")

        def connect_to_test_database():
            connection = sqlite3.connect(cls.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        cls.connect_to_test_database = connect_to_test_database
        cls.db_patch = patch.object(main, "get_db", side_effect=connect_to_test_database)
        cls.db_patch.start()
        cls._create_schema()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        os.unlink(cls.db_path)

    @classmethod
    def _create_schema(cls):
        connection = cls.connect_to_test_database()
        connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                age_confirmed INTEGER NOT NULL DEFAULT 0,
                eula_reviewed INTEGER NOT NULL DEFAULT 0,
                eula_agreed INTEGER NOT NULL DEFAULT 0,
                eula_version TEXT,
                consented_at TEXT,
                privacy_agreed INTEGER NOT NULL DEFAULT 1,
                -- Keep the fixture aligned with the active website policy
                -- version so tests for EULA-only flows are not blocked by a
                -- deliberately stale privacy consent.
                privacy_version TEXT DEFAULT '1.3',
                privacy_consented_at TEXT
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT 'p2',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_key TEXT,
                name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        connection.commit()
        connection.close()

    def setUp(self):
        self.client = self.app.test_client()

    @classmethod
    def _create_user(
        cls,
        username,
        *,
        eula_reviewed=0,
        eula_agreed=0,
        eula_version=None,
        consented_at=None,
    ):
        connection = cls.connect_to_test_database()
        cursor = connection.execute(
            """
            INSERT INTO users
                (username, password_hash, age_confirmed, eula_reviewed,
                 eula_agreed, eula_version, consented_at)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            """,
            (
                username,
                generate_password_hash("correct horse"),
                eula_reviewed,
                eula_agreed,
                eula_version,
                consented_at,
            ),
        )
        connection.commit()
        user_id = cursor.lastrowid
        connection.close()
        return user_id

    def _login_as(self, username):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": "correct horse"},
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_legacy_account_is_allowed_at_initial_eula_version(self):
        self._create_user("legacy-user")

        # Legacy accounts are grandfathered only while the initial EULA is
        # current. Once the version advances, the re-acceptance test below
        # covers the required update flow.
        with patch.object(main, "EULA_VERSION", "1.0"):
            login = self._login_as("legacy-user")
            self.assertFalse(login.json["user"]["eula_update_required"])
            self.assertIsNone(login.json["user"]["eula_version"])

            auth = self.client.get("/auth/me")
            self.assertEqual(auth.status_code, 200)
            self.assertFalse(auth.json["user"]["eula_update_required"])

            # A legacy account reaches protected handlers instead of being
            # blocked by the EULA check. Empty chat input is rejected by the
            # handler itself.
            files = self.client.get("/files")
            conversations = self.client.get("/conversations/latest")
            chat = self.client.post("/chat/stream", json={"messages": []})
            self.assertEqual(files.status_code, 200)
            self.assertEqual(conversations.status_code, 200)
            self.assertEqual(chat.status_code, 400)
            self.assertEqual(chat.json["error"], "No messages provided")

    def test_outdated_consent_blocks_protected_endpoints_and_auth_response(self):
        self._create_user(
            "outdated-user",
            eula_reviewed=1,
            eula_agreed=1,
            eula_version="0.9",
            consented_at="2025-01-01T00:00:00+00:00",
        )
        login = self._login_as("outdated-user")

        self.assertTrue(login.json["user"]["eula_update_required"])
        auth = self.client.get("/auth/me")
        self.assertEqual(auth.status_code, 200)
        self.assertTrue(auth.json["user"]["eula_update_required"])
        self.assertEqual(auth.json["user"]["eula_version"], "0.9")

        for path, method, payload in (
            ("/files", self.client.get, None),
            ("/files/1/download", self.client.get, None),
            ("/files/1", self.client.delete, None),
            (
                "/conversations/save",
                self.client.post,
                {"messages": [{"role": "user", "content": "hello"}]},
            ),
            ("/conversations/latest", self.client.get, None),
            (
                "/chat/stream",
                self.client.post,
                {"messages": [{"role": "user", "content": "hello"}]},
            ),
        ):
            response = method(path, json=payload) if payload else method(path)
            self.assertEqual(response.status_code, 403, path)
            self.assertTrue(response.json["eula_update_required"], path)
            self.assertEqual(response.json["eula_version"], main.EULA_VERSION, path)

    def test_acceptance_requires_current_review_and_persists_explicit_acceptance(self):
        self._create_user(
            "acceptance-user",
            eula_reviewed=1,
            eula_agreed=1,
            eula_version="0.9",
            consented_at="2025-01-01T00:00:00+00:00",
        )
        self._login_as("acceptance-user")

        invalid = self.client.post(
            "/auth/accept-eula",
            json={
                "eula_reviewed": True,
                "eula_agreed": True,
                "eula_version": "0.9",
            },
        )
        self.assertEqual(invalid.status_code, 400)

        accepted = self.client.post(
            "/auth/accept-eula",
            json={
                "eula_reviewed": True,
                "eula_agreed": True,
                "eula_version": main.EULA_VERSION,
            },
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json["ok"])
        self.assertFalse(accepted.json["user"]["eula_update_required"])
        self.assertEqual(accepted.json["user"]["eula_version"], main.EULA_VERSION)

        connection = type(self).connect_to_test_database()
        row = connection.execute(
            """
            SELECT eula_reviewed, eula_agreed, eula_version, consented_at
            FROM users WHERE username = ?
            """,
            ("acceptance-user",),
        ).fetchone()
        connection.close()
        self.assertEqual(row["eula_reviewed"], 1)
        self.assertEqual(row["eula_agreed"], 1)
        self.assertEqual(row["eula_version"], main.EULA_VERSION)
        self.assertTrue(row["consented_at"])

        self.assertEqual(self.client.get("/files").status_code, 200)

    def test_outdated_privacy_consent_blocks_protected_endpoints(self):
        user_id = self._create_user(
            "outdated-privacy-user",
            eula_reviewed=1,
            eula_agreed=1,
            eula_version=main.EULA_VERSION,
            consented_at="2025-01-01T00:00:00+00:00",
        )
        connection = type(self).connect_to_test_database()
        connection.execute(
            """
            UPDATE users
            SET privacy_agreed = 1, privacy_version = '1.0',
                privacy_consented_at = '2025-01-01T00:00:00+00:00'
            WHERE id = ?
            """,
            (user_id,),
        )
        connection.commit()
        connection.close()

        login = self._login_as("outdated-privacy-user")
        self.assertTrue(login.json["user"]["privacy_update_required"])
        self.assertFalse(login.json["user"]["eula_update_required"])

        response = self.client.get("/files")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json["privacy_update_required"])
        self.assertEqual(response.json["privacy_version"], main.PRIVACY_VERSION)

    def test_privacy_acceptance_requires_current_review_and_persists_timestamp(self):
        user_id = self._create_user(
            "privacy-acceptance-user",
            eula_reviewed=1,
            eula_agreed=1,
            eula_version=main.EULA_VERSION,
            consented_at="2025-01-01T00:00:00+00:00",
        )
        connection = type(self).connect_to_test_database()
        connection.execute(
            "UPDATE users SET privacy_agreed = 1, privacy_version = '1.0' WHERE id = ?",
            (user_id,),
        )
        connection.commit()
        connection.close()
        self._login_as("privacy-acceptance-user")

        invalid = self.client.post(
            "/auth/accept-privacy",
            json={
                "privacy_reviewed": True,
                "privacy_agreed": True,
                "privacy_version": "1.0",
            },
        )
        self.assertEqual(invalid.status_code, 400)

        accepted = self.client.post(
            "/auth/accept-privacy",
            json={
                "privacy_reviewed": True,
                "privacy_agreed": True,
                "privacy_version": main.PRIVACY_VERSION,
            },
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json["ok"])
        self.assertFalse(accepted.json["user"]["privacy_update_required"])
        self.assertEqual(accepted.json["user"]["privacy_version"], main.PRIVACY_VERSION)

        connection = type(self).connect_to_test_database()
        row = connection.execute(
            """
            SELECT privacy_agreed, privacy_version, privacy_consented_at
            FROM users WHERE username = ?
            """,
            ("privacy-acceptance-user",),
        ).fetchone()
        connection.close()
        self.assertEqual(row["privacy_agreed"], 1)
        self.assertEqual(row["privacy_version"], main.PRIVACY_VERSION)
        self.assertTrue(row["privacy_consented_at"])
        self.assertEqual(self.client.get("/files").status_code, 200)

    def test_current_privacy_consent_does_not_block_legacy_eula_flow(self):
        self._create_user(
            "current-privacy-user",
            eula_reviewed=1,
            eula_agreed=1,
            eula_version=main.EULA_VERSION,
            consented_at="2025-01-01T00:00:00+00:00",
        )
        login = self._login_as("current-privacy-user")
        self.assertFalse(login.json["user"]["privacy_update_required"])
        self.assertEqual(self.client.get("/files").status_code, 200)

    def test_chat_page_contains_auth_and_eula_browser_gates(self):
        response = self.client.get("/chat")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('id="auth-gate"', page)
        self.assertIn('id="eula-gate"', page)
        self.assertIn('id="eula-gate-review"', page)
        self.assertIn('id="eula-gate-accept"', page)
        self.assertIn('id="privacy-gate"', page)
        self.assertIn('id="privacy-gate-review"', page)
        self.assertIn('id="privacy-gate-accept"', page)
        self.assertIn(
            f"currentEulaVersion = {json.dumps(main.EULA_VERSION)}",
            page,
        )
        self.assertIn(
            f"currentPrivacyVersion = {json.dumps(main.PRIVACY_VERSION)}",
            page,
        )


if __name__ == "__main__":
    unittest.main()