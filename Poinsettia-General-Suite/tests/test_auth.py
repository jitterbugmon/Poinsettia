import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import main


class AccountPersistenceTests(unittest.TestCase):
    """Regression coverage for locally persisted signup and login."""

    @classmethod
    def setUpClass(cls):
        database = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        database.close()
        cls.db_path = database.name
        cls.app = main.app
        cls.app.config.update(TESTING=True, SECRET_KEY="auth-test-secret")

        def connect_to_test_database():
            connection = sqlite3.connect(cls.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        cls.connect_to_test_database = connect_to_test_database
        cls.db_patch = patch.object(main, "get_db", side_effect=connect_to_test_database)
        cls.db_patch.start()
        connection = connect_to_test_database()
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
                privacy_agreed INTEGER NOT NULL DEFAULT 0,
                privacy_version TEXT,
                privacy_consented_at TEXT
            );
            """
        )
        connection.commit()
        connection.close()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        os.unlink(cls.db_path)

    def setUp(self):
        self.client = self.app.test_client()

    def _signup_payload(self, username):
        return {
            "username": username,
            "password": "correct horse",
            "age_confirmed": True,
            "eula_reviewed": True,
            "eula_agreed": True,
            "eula_version": main.EULA_VERSION,
            "privacy_agreed": True,
            "privacy_version": main.PRIVACY_VERSION,
        }

    def test_signup_persists_and_new_client_can_login_after_session_reset(self):
        username = "saved-account"
        signup = self.client.post("/auth/signup", json=self._signup_payload(username))

        self.assertEqual(signup.status_code, 200)
        self.assertEqual(signup.json["user"]["username"], username)

        connection = type(self).connect_to_test_database()
        row = connection.execute(
            "SELECT username, password_hash, eula_version, privacy_version "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        connection.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["username"], username)
        self.assertTrue(row["password_hash"])
        self.assertEqual(row["eula_version"], main.EULA_VERSION)
        self.assertEqual(row["privacy_version"], main.PRIVACY_VERSION)

        # A fresh client proves authentication comes from SQLite, not only
        # from the signup request's in-memory session.
        fresh_client = self.app.test_client()
        login = fresh_client.post(
            "/auth/login",
            json={"username": username, "password": "correct horse"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json["user"]["username"], username)

    def test_duplicate_username_is_the_only_signup_conflict_reported_as_taken(self):
        username = "duplicate-account"
        first = self.client.post("/auth/signup", json=self._signup_payload(username))
        self.assertEqual(first.status_code, 200)

        duplicate = self.app.test_client().post(
            "/auth/signup",
            json=self._signup_payload(username),
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json["error"], "That username is already taken.")


if __name__ == "__main__":
    unittest.main()