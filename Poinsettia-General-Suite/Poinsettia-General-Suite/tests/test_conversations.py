import os
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ModuleNotFoundError:
    PlaywrightError = Exception
    expect = None
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

import main


class ConversationCrudTests(unittest.TestCase):
    """Coverage for authenticated, owner-scoped multi-chat operations."""

    @classmethod
    def setUpClass(cls):
        database = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        database.close()
        cls.db_path = database.name
        cls.app = main.app
        cls.app.config.update(TESTING=True, SECRET_KEY="conversation-test-secret")

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        connection.execute(
            """
            INSERT INTO users
                (username, password_hash, eula_version, privacy_version)
            VALUES (?, ?, ?, ?)
            """,
            ("chat-owner", generate_password_hash("correct horse"), main.EULA_VERSION, main.PRIVACY_VERSION),
        )
        connection.execute(
            """
            INSERT INTO users
                (username, password_hash, eula_version, privacy_version)
            VALUES (?, ?, ?, ?)
            """,
            ("other-owner", generate_password_hash("correct horse"), main.EULA_VERSION, main.PRIVACY_VERSION),
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
        response = self.client.post(
            "/auth/login",
            json={"username": "chat-owner", "password": "correct horse"},
        )
        self.assertEqual(response.status_code, 200)
        connection = type(self).connect_to_test_database()
        connection.execute("DELETE FROM conversations")
        connection.commit()
        connection.close()

    @staticmethod
    def _conversation_item(page, mode, title=None):
        item = page.locator(".conversation-item").filter(
            has=page.locator(".conversation-mode").filter(has_text=mode)
        )
        if title is not None:
            item = item.filter(
                has=page.locator(".conversation-name").filter(has_text=title)
            )
        return item

    def test_browser_chat_switching_and_responsive_sidebar(self):
        """Exercise signed-in chat CRUD, async switching, and sidebar overlays."""
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

            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            def mock_chat_stream(route):
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"},
                    body=(
                        'data: {"text":"Browser response"}\n\n'
                        'data: {"done":true}\n\n'
                    ),
                )

            page.route("**/chat/stream", mock_chat_stream)
            try:
                page.goto(f"{self.base_url}/chat", wait_until="domcontentloaded")
                page.locator("#auth-gate-open").click()
                page.locator("#signin-username").fill("chat-owner")
                page.locator("#signin-password").fill("correct horse")
                page.locator("#auth-signin-form").locator("button[type=submit]").click()
                expect(page.locator("#header-user-chip")).to_be_visible()

                sidebar = page.locator("#conversation-sidebar")
                sidebar_toggle = page.locator("#conversation-sidebar-toggle")
                sidebar_toggle.click()
                expect(sidebar).to_have_class(re.compile(r"\bopen\b"))

                # Create a P2 chat through the sidebar and let the browser's
                # normal send/save flow generate its title.
                page.locator("#new-chat-btn").click()
                p2_new = self._conversation_item(page, "P2", "New chat")
                expect(p2_new).to_have_count(1)
                page.locator("#conversation-sidebar-close").click()
                page.locator("#chat-input").fill("P2 browser title")
                page.locator("#send-button").click()
                p2 = self._conversation_item(page, "P2", "P2 browser title")
                expect(p2).to_have_count(1)
                expect(page.locator(".user-message").last).to_have_text("P2 browser title")

                # Create a separate P3 chat, then switch back and forth by
                # selecting the saved chats to cover async conversation loads.
                page.locator("#p3-btn").click()
                expect(page.locator("#p3-btn")).to_have_class(re.compile(r"\bactive\b"))
                sidebar_toggle.click()
                expect(sidebar).to_have_class(re.compile(r"\bopen\b"))
                page.locator("#new-chat-btn").click()
                p3_new = self._conversation_item(page, "P3", "New chat")
                expect(p3_new).to_have_count(1)
                page.locator("#conversation-sidebar-close").click()
                page.locator("#chat-input").fill("P3 browser title")
                page.locator("#send-button").click()
                p3 = self._conversation_item(page, "P3", "P3 browser title")
                expect(p3).to_have_count(1)

                for mode, label, prompt in [
                    ("p4-fax", "P4 Fax", "P4 Fax browser title"),
                    ("p4-candor", "P4 Candor", "P4 Candor browser title"),
                ]:
                    page.locator("#model-selector").select_option(mode)
                    sidebar_toggle.click()
                    page.locator("#new-chat-btn").click()
                    expect(self._conversation_item(page, label, "New chat")).to_have_count(1)
                    page.locator("#conversation-sidebar-close").click()
                    page.locator("#chat-input").fill(prompt)
                    page.locator("#send-button").click()
                    expect(self._conversation_item(page, label, prompt)).to_have_count(1)

                # Search matches both saved titles and the first user message,
                # while keeping the mode labels visible in the filtered list.
                search = page.locator("#conversation-search")
                search.fill("P2 browser title")
                expect(self._conversation_item(page, "P2", "P2 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P3")).to_have_count(0)
                search.fill("P3 browser title")
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P2")).to_have_count(0)
                search.fill("P4 Fax browser title")
                expect(self._conversation_item(page, "P4 Fax", "P4 Fax browser title")).to_have_count(1)
                search.fill("P4 Candor browser title")
                expect(self._conversation_item(page, "P4 Candor", "P4 Candor browser title")).to_have_count(1)
                search.fill("")

                sidebar_toggle.click()
                expect(sidebar).to_have_class(re.compile(r"\bopen\b"))
                p2 = self._conversation_item(page, "P2", "P2 browser title")
                p2.locator(".conversation-select").click()
                expect(page.locator("#p2-btn")).to_have_class(re.compile(r"\bactive\b"))
                expect(page.locator(".user-message").last).to_have_text("P2 browser title")

                p3 = self._conversation_item(page, "P3", "P3 browser title")
                p3.locator(".conversation-select").click()
                expect(page.locator("#p3-btn")).to_have_class(re.compile(r"\bactive\b"))
                expect(page.locator(".user-message").last).to_have_text("P3 browser title")

                # A full reload must restore the signed-in user's selected
                # mode, active conversations, and message history from the
                # server rather than leaving a stale client-side chat.
                page.reload(wait_until="domcontentloaded")
                expect(page.locator("#header-user-chip")).to_be_visible()
                expect(page.locator("#model-selector")).to_have_value("p3-3.9")
                expect(self._conversation_item(page, "P2", "P2 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P4 Fax", "P4 Fax browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P4 Candor", "P4 Candor browser title")).to_have_count(1)
                expect(page.locator(".user-message").last).to_have_text("P3 browser title")

                sidebar_toggle = page.locator("#conversation-sidebar-toggle")
                sidebar_toggle.click()
                self._conversation_item(page, "P2", "P2 browser title").locator(
                    ".conversation-select"
                ).click()
                expect(page.locator("#p2-btn")).to_have_class(re.compile(r"\bactive\b"))
                expect(page.locator(".user-message").last).to_have_text("P2 browser title")
                expect(page.locator(".bot-message").last).to_contain_text("Browser response")
                self._conversation_item(page, "P3", "P3 browser title").locator(
                    ".conversation-select"
                ).click()
                expect(page.locator("#p3-btn")).to_have_class(re.compile(r"\bactive\b"))
                expect(page.locator(".user-message").last).to_have_text("P3 browser title")
                expect(page.locator(".bot-message").last).to_contain_text("Browser response")
                self._conversation_item(page, "P4 Fax", "P4 Fax browser title").locator(
                    ".conversation-select"
                ).click()
                expect(page.locator("#model-selector")).to_have_value("p4-fax")
                expect(page.locator(".user-message").last).to_have_text("P4 Fax browser title")
                expect(page.locator(".bot-message").last).to_contain_text("Browser response")
                self._conversation_item(page, "P4 Candor", "P4 Candor browser title").locator(
                    ".conversation-select"
                ).click()
                expect(page.locator("#model-selector")).to_have_value("p4-candor")
                expect(page.locator(".user-message").last).to_have_text("P4 Candor browser title")
                expect(page.locator(".bot-message").last).to_contain_text("Browser response")
                page.locator("#conversation-sidebar-close").click()

                # Signing out must remove the authenticated chat list and
                # signing back in must reload the owner's server state,
                # without adopting guest-local history.
                page.locator("#header-signout-btn").click()
                expect(page.locator("#auth-gate-open")).to_be_visible()
                page.evaluate(
                    """() => {
                        localStorage.setItem(
                            "poinsettia_histories_guest",
                            JSON.stringify({
                                p2: [{role: "user", content: "Guest-only state"}],
                                p3: []
                            })
                        );
                        localStorage.setItem("poinsettia_current_mode_guest", "p2");
                    }"""
                )
                page.reload(wait_until="domcontentloaded")
                expect(page.locator(".user-message").last).to_have_text("Guest-only state")

                page.locator("#auth-gate-open").click()
                page.locator("#signin-username").fill("chat-owner")
                page.locator("#signin-password").fill("correct horse")
                page.locator("#auth-signin-form").locator("button[type=submit]").click()
                expect(page.locator("#header-user-chip")).to_be_visible()
                expect(page.locator("#model-selector")).to_have_value("p4-candor")
                expect(page.locator(".user-message").last).to_have_text("P4 Candor browser title")
                expect(page.locator(".user-message").filter(has_text="Guest-only state")).to_have_count(0)
                expect(self._conversation_item(page, "P2", "P2 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P4 Fax", "P4 Fax browser title")).to_have_count(1)
                expect(self._conversation_item(page, "P4 Candor", "P4 Candor browser title")).to_have_count(1)

                # Keep P2 selected while exercising metadata actions on both
                # chats, so deleting the inactive P3 chat does not clear the
                # visible conversation.
                sidebar = page.locator("#conversation-sidebar")
                sidebar_toggle = page.locator("#conversation-sidebar-toggle")
                sidebar_toggle.click()
                p2 = self._conversation_item(page, "P2", "P2 browser title")
                p2.locator(".conversation-select").click()
                expect(page.locator("#p2-btn")).to_have_class(re.compile(r"\bactive\b"))
                expect(page.locator(".user-message").last).to_have_text("P2 browser title")

                # Rename and pin P2, verifying the in-app dialog, focus
                # restoration, dismissal paths, and asynchronous list update.
                p2 = self._conversation_item(page, "P2", "P2 browser title")
                rename_button = p2.get_by_role("button", name="Rename chat", exact=True)
                rename_button.click()
                rename_modal = page.locator("#chat-rename-modal")
                expect(rename_modal).to_be_visible()
                expect(rename_modal.locator("#chat-rename-input")).to_be_focused()
                rename_modal.click(position={"x": 5, "y": 5})
                expect(rename_modal).to_be_hidden()
                expect(rename_button).to_be_focused()

                rename_button.click()
                rename_modal.get_by_role("button", name="Cancel", exact=True).click()
                expect(rename_modal).to_be_hidden()
                expect(rename_button).to_be_focused()

                rename_button.click()
                page.keyboard.press("Escape")
                expect(rename_modal).to_be_hidden()
                expect(rename_button).to_be_focused()

                rename_button.click()
                rename_modal.locator("#chat-rename-input").fill("Renamed P2 chat")
                rename_modal.get_by_role("button", name="Save", exact=True).click()
                renamed_p2 = self._conversation_item(page, "P2", "Renamed P2 chat")
                expect(renamed_p2).to_have_count(1)

                renamed_p2.get_by_role("button", name="Pin chat").click()
                renamed_p2 = self._conversation_item(page, "P2", "Renamed P2 chat")
                expect(renamed_p2.get_by_role("button", name="Unpin chat")).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(renamed_p2).to_have_class(re.compile(r"\bpinned\b"))
                expect(page.locator(".conversation-item").first).to_have_attribute(
                    "data-conversation-id", renamed_p2.get_attribute("data-conversation-id")
                )
                pinned_style = renamed_p2.evaluate(
                    """(element) => ({
                        connected: element.isConnected,
                        className: element.className,
                        background: getComputedStyle(element).getPropertyValue('background-color'),
                        shadow: getComputedStyle(element).getPropertyValue('box-shadow')
                    })"""
                )
                self.assertIn("255, 213, 79", pinned_style["background"], pinned_style)

                # Delete the P3 chat, covering cancellation and dismissal
                # before confirming it disappears without disturbing the
                # currently selected P2 conversation.
                p3 = self._conversation_item(page, "P3", "P3 browser title")
                delete_button = p3.get_by_role("button", name="Delete chat", exact=True)
                delete_button.click()
                delete_modal = page.locator("#chat-delete-modal")
                expect(delete_modal).to_be_visible()
                expect(delete_modal.locator("#chat-delete-name")).to_have_text("P3 browser title")
                delete_confirm = delete_modal.locator("#chat-delete-confirm")
                expect(delete_confirm).to_be_focused()
                delete_modal.get_by_role("button", name="Cancel", exact=True).click()
                expect(delete_modal).to_be_hidden()
                expect(delete_button).to_be_focused()
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(1)

                delete_button.click()
                page.keyboard.press("Escape")
                expect(delete_modal).to_be_hidden()
                expect(delete_button).to_be_focused()

                delete_button.click()
                delete_modal.click(position={"x": 5, "y": 5})
                expect(delete_modal).to_be_hidden()
                expect(delete_button).to_be_focused()
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(1)

                delete_button.click()
                delete_confirm.click()
                expect(self._conversation_item(page, "P3", "P3 browser title")).to_have_count(0)
                expect(page.locator(".user-message").last).to_have_text("P2 browser title")

                # The conversation sidebar is fixed/overlay-based on desktop:
                # opening it must not change the chat area's geometry.
                page.locator("#conversation-sidebar-close").click()
                page.wait_for_timeout(350)
                desktop_closed = page.locator("main").bounding_box()
                sidebar_toggle.click()
                expect(sidebar).to_have_class(re.compile(r"\bopen\b"))
                desktop_open = page.locator("main").bounding_box()
                self.assertIsNotNone(desktop_closed)
                self.assertIsNotNone(desktop_open)
                self.assertEqual(
                    (desktop_closed["x"], desktop_closed["width"]),
                    (desktop_open["x"], desktop_open["width"]),
                )

                # On a narrow viewport the sidebar becomes a modal overlay
                # with a backdrop, while the main chat keeps the same width.
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator("#conversation-sidebar-close").click()
                page.wait_for_timeout(350)
                mobile_closed = page.locator("main").bounding_box()
                sidebar_toggle.click()
                expect(sidebar).to_have_class(re.compile(r"\bopen\b"))
                expect(page.locator("#conversation-sidebar-backdrop")).to_have_class(
                    re.compile(r"\bvisible\b")
                )
                mobile_open = page.locator("main").bounding_box()
                self.assertIsNotNone(mobile_closed)
                self.assertIsNotNone(mobile_open)
                self.assertEqual(
                    (mobile_closed["x"], mobile_closed["width"]),
                    (mobile_open["x"], mobile_open["width"]),
                )
                page.locator("#conversation-sidebar-close").click()
                page.wait_for_timeout(350)
                self.assertNotIn("open", sidebar.get_attribute("class") or "")
            finally:
                context.close()
                browser.close()

    def test_switching_back_waits_for_assistant_reply_to_save(self):
        """A pending assistant save must finish before reloading the prior chat."""
        if not PLAYWRIGHT_AVAILABLE:
            self.skipTest("Playwright is not installed in this environment")

        assistant_save_started = threading.Event()
        allow_assistant_save = threading.Event()
        original_save = self.app.view_functions["save_conversation"]

        def delayed_assistant_save():
            payload = main.request.get_json(silent=True) or {}
            if any(
                isinstance(message, dict) and message.get("role") == "assistant"
                for message in payload.get("messages", [])
            ):
                assistant_save_started.set()
                if not allow_assistant_save.wait(timeout=10):
                    raise TimeoutError("The test did not release the assistant save.")
            return original_save()

        with patch.dict(self.app.view_functions, {"save_conversation": delayed_assistant_save}):
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
                page.route(
                    "**/chat/stream",
                    lambda route: route.fulfill(
                        status=200,
                        content_type="text/event-stream",
                        body=(
                            'data: {"text":"Saved assistant reply"}\n\n'
                            'data: {"done":true}\n\n'
                        ),
                    ),
                )
                try:
                    page.goto(f"{self.base_url}/chat", wait_until="domcontentloaded")
                    page.locator("#auth-gate-open").click()
                    page.locator("#signin-username").fill("chat-owner")
                    page.locator("#signin-password").fill("correct horse")
                    page.locator("#auth-signin-form").locator("button[type=submit]").click()
                    expect(page.locator("#header-user-chip")).to_be_visible()

                    sidebar_toggle = page.locator("#conversation-sidebar-toggle")
                    sidebar_toggle.click()
                    page.locator("#new-chat-btn").click()
                    expect(self._conversation_item(page, "P2", "New chat")).to_have_count(1)
                    page.locator("#conversation-sidebar-close").click()
                    page.locator("#chat-input").fill("Race chat")
                    page.locator("#send-button").click()
                    expect(page.locator(".bot-message").last).to_contain_text("Saved assistant reply")
                    self.assertTrue(assistant_save_started.wait(timeout=5))

                    sidebar_toggle.click()
                    page.locator("#new-chat-btn").click()
                    expect(self._conversation_item(page, "P2", "New chat")).to_have_count(1)
                    old_chat = self._conversation_item(page, "P2", "Race chat")
                    conversation_id = int(old_chat.get_attribute("data-conversation-id"))
                    old_chat.locator(".conversation-select").click()
                    expect(page.locator("#chat-messages")).to_contain_text("Loading chat…")

                    connection = type(self).connect_to_test_database()
                    count = connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()[0]
                    connection.close()
                    self.assertEqual(count, 1)

                    allow_assistant_save.set()
                    expect(page.locator(".bot-message").last).to_contain_text("Saved assistant reply")
                    page.reload(wait_until="domcontentloaded")
                    expect(page.locator(".bot-message").last).to_contain_text("Saved assistant reply")

                    connection = type(self).connect_to_test_database()
                    roles = [
                        row[0] for row in connection.execute(
                            "SELECT role FROM messages WHERE conversation_id = ? ORDER BY id",
                            (conversation_id,),
                        )
                    ]
                    connection.close()
                    self.assertEqual(roles, ["user", "assistant"])
                finally:
                    allow_assistant_save.set()
                    browser.close()

    def test_browser_long_formatted_assistant_reply_is_not_clipped(self):
        """Keep long assistant bubbles inside the scrolling chat viewport."""
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

            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            long_reply = (
                "## Conversation layout check\n\n"
                + "This paragraph verifies that a long assistant response remains fully visible "
                "inside its bubble while the conversation history scrolls. " * 8
                + "\n\n**Important:** formatted text must contribute its full height.\n\n"
                + "| Section | Status |\n"
                + "| --- | --- |\n"
                + "| Assistant bubble | visible |\n"
                + "| Composer | visible |\n\n"
                + "The final paragraph confirms that content after the table is not clipped. "
                * 8
            )

            def mock_chat_stream(route):
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"},
                    body=(
                        "data: "
                        + json.dumps({"text": long_reply})
                        + "\n\n"
                        + 'data: {"done":true}\n\n'
                    ),
                )

            page.route("**/chat/stream", mock_chat_stream)
            try:
                page.goto(f"{self.base_url}/chat", wait_until="domcontentloaded")
                page.locator("#auth-gate-open").click()
                page.locator("#signin-username").fill("chat-owner")
                page.locator("#signin-password").fill("correct horse")
                page.locator("#auth-signin-form").locator("button[type=submit]").click()
                expect(page.locator("#header-user-chip")).to_be_visible()

                page.locator("#chat-input").fill("Check the long reply layout")
                page.locator("#send-button").click()

                assistant = page.locator(".bot-message").last
                expect(assistant).to_contain_text(
                    "The final paragraph confirms that content after the table is not clipped."
                )
                expect(assistant.locator("strong")).to_have_text("Important:")
                expect(assistant).to_contain_text(
                    "formatted text must contribute its full height."
                )
                expect(assistant.locator("table")).to_be_visible()

                metrics = page.evaluate(
                    """() => {
                        const messages = document.getElementById('chat-messages');
                        const composer = document.querySelector('.chat-input-container');
                        const assistant = document.querySelector('.bot-message:last-of-type');
                        const content = assistant.querySelector('.message-content');
                        const documentHeight = Math.max(
                            document.body.scrollHeight,
                            document.documentElement.scrollHeight
                        );
                        const composerBox = composer.getBoundingClientRect();
                        const messagesBox = messages.getBoundingClientRect();
                        return {
                            contentScrollHeight: content.scrollHeight,
                            contentClientHeight: content.clientHeight,
                            bubbleScrollHeight: assistant.scrollHeight,
                            bubbleClientHeight: assistant.clientHeight,
                            messagesScrollHeight: messages.scrollHeight,
                            messagesClientHeight: messages.clientHeight,
                            documentHeight,
                            viewportHeight: window.innerHeight,
                            composerTop: composerBox.top,
                            composerBottom: composerBox.bottom,
                            messagesBottom: messagesBox.bottom,
                            composerVisible: composerBox.top >= 0 &&
                                composerBox.bottom <= window.innerHeight
                        };
                    }"""
                )

                self.assertEqual(
                    metrics["contentScrollHeight"],
                    metrics["contentClientHeight"],
                    metrics,
                )
                self.assertEqual(
                    metrics["bubbleScrollHeight"],
                    metrics["bubbleClientHeight"],
                    metrics,
                )
                self.assertGreater(
                    metrics["messagesScrollHeight"],
                    metrics["messagesClientHeight"],
                    metrics,
                )
                self.assertLessEqual(metrics["documentHeight"], metrics["viewportHeight"], metrics)
                self.assertGreaterEqual(metrics["composerTop"], metrics["messagesBottom"] - 1, metrics)
                self.assertTrue(metrics["composerVisible"], metrics)
            finally:
                context.close()
                browser.close()

    def test_browser_streaming_formatted_reply_stays_contained(self):
        """Keep the viewport contained while formatted assistant text grows."""
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

            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            streamed_chunks = [
                "## First streamed section\n\n"
                + "This paragraph is intentionally long so the message list must scroll "
                "while the response is still arriving. " * 12
                + "\n\n",
                "**Mid-stream formatting remains visible.**\n\n"
                "| Check | State |\n"
                "| --- | --- |\n"
                "| Assistant bubble | growing |\n"
                "| Message list | scrolling |\n\n",
                "The final streamed section remains visible after the table. "
                "This marker confirms that later chunks are not clipped."
                * 6,
            ]
            page.add_init_script(
                """
                (() => {
                    const chunks = __STREAMED_CHUNKS__;
                    const realFetch = window.fetch.bind(window);

                    window.fetch = function(input, init) {
                        const requestUrl = typeof input === 'string' ? input : input.url;
                        if (!requestUrl.endsWith('/chat/stream')) {
                            return realFetch(input, init);
                        }

                        const encoder = new TextEncoder();
                        return Promise.resolve(new Response(
                            new ReadableStream({
                                start(controller) {
                                    chunks.forEach((chunk, index) => {
                                        window.setTimeout(() => {
                                            controller.enqueue(encoder.encode(
                                                'data: ' + JSON.stringify({text: chunk}) + '\\n\\n'
                                            ));
                                            if (index === chunks.length - 1) {
                                                window.setTimeout(() => {
                                                    controller.enqueue(encoder.encode(
                                                        'data: {"done":true}\\n\\n'
                                                    ));
                                                    controller.close();
                                                }, 120);
                                            }
                                        }, index * 180);
                                    });
                                }
                            }),
                            {
                                status: 200,
                                headers: {'Content-Type': 'text/event-stream'}
                            }
                        ));
                    };
                })();
                """.replace("__STREAMED_CHUNKS__", json.dumps(streamed_chunks))
            )

            try:
                page.goto(f"{self.base_url}/chat", wait_until="domcontentloaded")
                page.locator("#auth-gate-open").click()
                page.locator("#signin-username").fill("chat-owner")
                page.locator("#signin-password").fill("correct horse")
                page.locator("#auth-signin-form").locator("button[type=submit]").click()
                expect(page.locator("#header-user-chip")).to_be_visible()

                page.locator("#chat-input").fill("Check the streaming layout")
                page.locator("#send-button").click()
                assistant = page.locator(".bot-message").last

                def read_viewport_metrics():
                    return page.evaluate(
                        """() => {
                            const messages = document.getElementById('chat-messages');
                            const composer = document.querySelector('.chat-input-container');
                            const assistant = document.querySelector('.bot-message:last-of-type');
                            const content = assistant.querySelector('.message-content');
                            const composerBox = composer.getBoundingClientRect();
                            const messagesBox = messages.getBoundingClientRect();
                            const documentHeight = Math.max(
                                document.body.scrollHeight,
                                document.documentElement.scrollHeight
                            );
                            return {
                                contentScrollHeight: content.scrollHeight,
                                contentClientHeight: content.clientHeight,
                                bubbleScrollHeight: assistant.scrollHeight,
                                bubbleClientHeight: assistant.clientHeight,
                                messagesScrollHeight: messages.scrollHeight,
                                messagesClientHeight: messages.clientHeight,
                                messagesScrollTop: messages.scrollTop,
                                documentHeight,
                                viewportHeight: window.innerHeight,
                                composerTop: composerBox.top,
                                composerBottom: composerBox.bottom,
                                messagesBottom: messagesBox.bottom,
                                composerVisible: composerBox.top >= 0 &&
                                    composerBox.bottom <= window.innerHeight,
                                messagesOverflowY: getComputedStyle(messages).overflowY,
                                bodyOverflowY: getComputedStyle(document.body).overflowY,
                                atMessagesBottom: messages.scrollTop + messages.clientHeight >=
                                    messages.scrollHeight - 1
                            };
                        }"""
                    )

                def assert_contained(metrics):
                    self.assertEqual(
                        metrics["contentScrollHeight"],
                        metrics["contentClientHeight"],
                        metrics,
                    )
                    self.assertEqual(
                        metrics["bubbleScrollHeight"],
                        metrics["bubbleClientHeight"],
                        metrics,
                    )
                    self.assertGreater(
                        metrics["messagesScrollHeight"],
                        metrics["messagesClientHeight"],
                        metrics,
                    )
                    self.assertLessEqual(metrics["documentHeight"], metrics["viewportHeight"], metrics)
                    self.assertGreaterEqual(metrics["composerTop"], metrics["messagesBottom"] - 1, metrics)
                    self.assertTrue(metrics["composerVisible"], metrics)
                    self.assertEqual(metrics["messagesOverflowY"], "auto", metrics)
                    self.assertEqual(metrics["bodyOverflowY"], "hidden", metrics)
                    self.assertTrue(metrics["atMessagesBottom"], metrics)

                for marker in (
                    "First streamed section",
                    "Mid-stream formatting remains visible.",
                    "The final streamed section remains visible after the table.",
                ):
                    page.wait_for_function(
                        """marker => {
                            const content = document.querySelector(
                                '.bot-message:last-of-type .message-content'
                            );
                            return content && content.textContent.includes(marker);
                        }""",
                        arg=marker,
                    )
                    assert_contained(read_viewport_metrics())

                expect(page.locator("#send-button")).to_be_visible()
                expect(page.locator("#chat-input")).to_be_enabled()
                assert_contained(read_viewport_metrics())
            finally:
                context.close()
                browser.close()

    def test_create_save_title_list_pin_load_and_delete(self):
        created = self.client.post("/conversations", json={"mode": "p2"})
        self.assertEqual(created.status_code, 201)
        conversation = created.json["conversation"]
        conversation_id = conversation["id"]
        self.assertEqual(conversation["title"], "New chat")

        saved = self.client.post(
            "/conversations/save",
            json={
                "conversation_id": conversation_id,
                "mode": "p2",
                "messages": [
                    {"role": "user", "content": "Explain the long term support plan"},
                    {"role": "assistant", "content": "Here is a concise overview."},
                ],
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved.json["conversation"]["title"],
            "Explain the long term support plan",
        )
        self.assertEqual(
            saved.json["conversation"]["first_message"],
            "Explain the long term support plan",
        )

        loaded = self.client.get(f"/conversations/{conversation_id}")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(len(loaded.json["messages"]), 2)

        renamed = self.client.patch(
            f"/conversations/{conversation_id}",
            json={"title": "Support notes", "pinned": True},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json["conversation"]["title"], "Support notes")
        self.assertTrue(renamed.json["conversation"]["pinned"])

        listed = self.client.get("/conversations")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json["conversations"][0]["id"], conversation_id)
        self.assertTrue(listed.json["conversations"][0]["pinned"])
        self.assertEqual(
            listed.json["conversations"][0]["first_message"],
            "Explain the long term support plan",
        )

        deleted = self.client.delete(f"/conversations/{conversation_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/conversations/{conversation_id}").status_code, 404)

    def test_conversation_search_matches_title_or_first_message_for_owner_only(self):
        first = self.client.post("/conversations", json={"mode": "p2"}).json["conversation"]
        self.client.post(
            "/conversations/save",
            json={
                "conversation_id": first["id"],
                "mode": "p2",
                "messages": [
                    {"role": "user", "content": "Quarterly planning notes"},
                    {"role": "assistant", "content": "Saved."},
                ],
            },
        )
        self.client.patch(
            f"/conversations/{first['id']}",
            json={"title": "Finance archive", "pinned": True},
        )

        second = self.client.post("/conversations", json={"mode": "p3"}).json["conversation"]
        self.client.post(
            "/conversations/save",
            json={
                "conversation_id": second["id"],
                "mode": "p3",
                "messages": [
                    {"role": "user", "content": "Weekend research"},
                    {"role": "assistant", "content": "Saved."},
                ],
            },
        )

        connection = type(self).connect_to_test_database()
        other_user_id = connection.execute(
            "SELECT id FROM users WHERE username = ?", ("other-owner",)
        ).fetchone()["id"]
        cursor = connection.execute(
            "INSERT INTO conversations (user_id, mode, title, pinned) VALUES (?, ?, ?, ?)",
            (other_user_id, "p2", "Finance secret", 1),
        )
        other_conversation_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (other_conversation_id, "user", "Quarterly private notes"),
        )
        connection.commit()
        connection.close()

        title_match = self.client.get("/conversations?search=finance")
        self.assertEqual(title_match.status_code, 200)
        self.assertEqual(
            [item["id"] for item in title_match.json["conversations"]],
            [first["id"]],
        )
        self.assertTrue(title_match.json["conversations"][0]["pinned"])
        self.assertEqual(title_match.json["conversations"][0]["mode"], "p2")

        message_match = self.client.get("/conversations?search=quarterly")
        self.assertEqual(message_match.status_code, 200)
        self.assertEqual(
            [item["id"] for item in message_match.json["conversations"]],
            [first["id"]],
        )

    def test_conversation_cannot_be_read_by_another_user(self):
        created = self.client.post("/conversations", json={"mode": "p3"})
        self.assertEqual(created.status_code, 201)
        conversation_id = created.json["conversation"]["id"]

        self.client.post("/auth/logout")
        login = self.client.post(
            "/auth/login",
            json={"username": "other-owner", "password": "correct horse"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.client.get(f"/conversations/{conversation_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()