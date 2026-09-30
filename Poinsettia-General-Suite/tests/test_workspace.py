import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import main
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ModuleNotFoundError:
    PlaywrightError = Exception
    expect = None
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False


class WorkspaceFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        database.close()
        cls.db_path = database.name
        cls.app = main.app
        cls.app.config.update(TESTING=True, SECRET_KEY="workspace-test-secret")

        def connect_to_test_database():
            connection = sqlite3.connect(cls.db_path)
            connection.row_factory = sqlite3.Row
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
                age_confirmed INTEGER NOT NULL DEFAULT 1,
                eula_reviewed INTEGER NOT NULL DEFAULT 1,
                eula_agreed INTEGER NOT NULL DEFAULT 1,
                eula_version TEXT,
                consented_at TEXT,
                privacy_agreed INTEGER NOT NULL DEFAULT 1,
                privacy_version TEXT,
                privacy_consented_at TEXT
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT 'p2',
                title TEXT NOT NULL DEFAULT 'New chat',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_key TEXT,
                name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                path TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.executemany(
            """INSERT INTO users
               (username, password_hash, eula_version, privacy_version)
               VALUES (?, ?, ?, ?)""",
            [
                ("workspace-owner", generate_password_hash("correct horse"),
                 main.EULA_VERSION, main.PRIVACY_VERSION),
                ("other-owner", generate_password_hash("correct horse"),
                 main.EULA_VERSION, main.PRIVACY_VERSION),
            ],
        )
        connection.commit()
        connection.close()
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server_thread.join(timeout=5)
        cls.db_patch.stop()
        os.unlink(cls.db_path)

    def setUp(self):
        self.client = self.app.test_client()
        self.temp_directory = tempfile.mkdtemp(prefix="poinsettia-workspace-")
        self.text_file_path = os.path.join(self.temp_directory, "draft.txt")
        with open(self.text_file_path, "w", encoding="utf-8") as document:
            document.write("A first draft.\nA second line.")
        connection = type(self).connect_to_test_database()
        cursor = connection.execute(
            """INSERT INTO files (user_id, session_key, name, mime_type, path, size)
               VALUES (1, NULL, 'draft.txt', 'text/plain', ?, ?)""",
            (self.text_file_path, os.path.getsize(self.text_file_path)),
        )
        self.file_id = cursor.lastrowid
        connection.commit()
        connection.close()
        with self.client.session_transaction() as user_session:
            user_session["user_id"] = 1

    def tearDown(self):
        connection = type(self).connect_to_test_database()
        connection.execute("DELETE FROM files WHERE user_id = 1")
        connection.commit()
        connection.close()
        shutil.rmtree(self.temp_directory, ignore_errors=True)

    def test_owner_can_open_and_save_rich_text_without_unsafe_markup(self):
        opened = self.client.get(f"/files/{self.file_id}/content")
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.json["content"], "A first draft.\nA second line.")

        saved = self.client.put(
            f"/files/{self.file_id}/content",
            json={
                "content": (
                    '<p><strong>Formatted text</strong></p>'
                    '<script>alert("unsafe")</script>'
                    '<img src="x" onerror="alert(1)">'
                    '<a href="javascript:alert(1)">unsafe link</a>'
                )
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json["file"]["name"], "draft.html")
        self.assertEqual(saved.json["file"]["mime_type"], "text/html")
        self.assertFalse(os.path.exists(self.text_file_path))

        reopened = self.client.get(f"/files/{self.file_id}/content")
        self.assertEqual(reopened.status_code, 200)
        self.assertIn("<strong>Formatted text</strong>", reopened.json["content"])
        self.assertNotIn("<script", reopened.json["content"])
        self.assertNotIn("<img", reopened.json["content"])
        self.assertNotIn("javascript:", reopened.json["content"])

    def test_file_content_is_private_to_its_owner(self):
        another_client = self.app.test_client()
        with another_client.session_transaction() as user_session:
            user_session["user_id"] = 2
        response = another_client.get(f"/files/{self.file_id}/content")
        self.assertEqual(response.status_code, 404)

    def test_workspace_routes_require_sign_in_and_reject_binary_files(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(f"/files/{self.file_id}/content").status_code, 401)

        binary_path = os.path.join(self.temp_directory, "archive.zip")
        with open(binary_path, "wb") as archive:
            archive.write(b"binary")
        connection = type(self).connect_to_test_database()
        cursor = connection.execute(
            """INSERT INTO files (user_id, session_key, name, mime_type, path, size)
               VALUES (1, NULL, 'archive.zip', 'application/zip', ?, 6)""",
            (binary_path,),
        )
        connection.commit()
        connection.close()
        response = self.client.get(f"/files/{cursor.lastrowid}/content")
        self.assertEqual(response.status_code, 415)

    def test_browser_opens_workspace_from_files_and_preserves_formatting(self):
        if not PLAYWRIGHT_AVAILABLE:
            self.skipTest("Playwright is not installed in this environment")

        with sync_playwright() as playwright:
            launch_options = {"headless": True, "args": ["--no-sandbox"]}
            chromium = shutil.which("chromium") or shutil.which("chromium-browser")
            if chromium:
                launch_options["executable_path"] = chromium
            try:
                browser = playwright.chromium.launch(**launch_options)
            except PlaywrightError as error:
                self.skipTest(f"Chromium is unavailable: {error}")

            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            try:
                page.goto(f"{self.base_url}/chat", wait_until="domcontentloaded")
                expect(page.locator("#workspace-panel")).to_be_hidden()
                page.locator("#auth-gate-open").click()
                page.locator("#signin-username").fill("workspace-owner")
                page.locator("#signin-password").fill("correct horse")
                page.locator("#auth-signin-form").locator("button[type=submit]").click()
                expect(page.locator("#header-user-chip")).to_be_visible()

                page.locator("#files-btn").click()
                expect(page.locator("#files-panel")).to_be_visible()
                edit_button = page.locator(".files-panel-edit")
                expect(edit_button).to_have_count(1)
                edit_button.click()
                expect(page.locator("#workspace-panel")).to_be_visible()
                expect(page.locator("#workspace-document-name")).to_have_text("draft.txt")

                editor = page.locator("#workspace-editor")
                editor.evaluate(
                    """element => {
                        element.focus();
                        const range = document.createRange();
                        range.selectNodeContents(element);
                        const selection = window.getSelection();
                        selection.removeAllRanges();
                        selection.addRange(range);
                    }"""
                )
                page.locator('#workspace-toolbar button[data-command="bold"]').click()
                expect(editor.locator("b, strong")).to_have_count(1)

                editor.evaluate(
                    """element => {
                        const range = document.createRange();
                        range.selectNodeContents(element);
                        const selection = window.getSelection();
                        selection.removeAllRanges();
                        selection.addRange(range);
                    }"""
                )
                page.locator("#workspace-font-size").select_option("24px")
                expect(editor.locator('[style*="font-size"]')).to_have_count(1)

                page.locator("#workspace-save").click()
                expect(page.locator("#workspace-status")).to_have_text("Saved")
                expect(page.locator("#workspace-document-name")).to_have_text("draft.html")

                page.locator("#workspace-back").click()
                expect(page.locator("#files-panel")).to_be_visible()
                expect(page.locator(".files-panel-name")).to_have_text("draft.html")
                page.locator(".files-panel-edit").click()
                expect(page.locator("#workspace-panel")).to_be_visible()
                expect(editor.locator("b, strong")).to_have_count(1)
                expect(editor.locator('[style*="font-size"]')).to_have_count(1)
                self.assertEqual(page_errors, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()