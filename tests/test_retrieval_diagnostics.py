"""Portable tests for the privacy-safe Windows retrieval log."""

import hashlib
import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import main

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_release"))
from poinsettia_windows import diagnostics


class RetrievalDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.logger = logging.getLogger(diagnostics.LOGGER_NAME)
        self.original_handlers = self.logger.handlers[:]
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self.logger.handlers = []
        self.path = diagnostics.configure_diagnostics(Path(self.directory.name))

    def tearDown(self):
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate
        self.directory.cleanup()

    def read_log(self):
        for handler in self.logger.handlers:
            handler.flush()
        return self.path.read_text(encoding="utf-8")

    def test_structured_failure_records_exclude_private_payloads(self):
        main._retrieval_event(
            "search_error", endpoint="HTML POST", reason="tls", error_type="SSLError",
            query="DO_NOT_LOG_QUERY", url="https://private.test/DO_NOT_LOG_URL",
            cookie="DO_NOT_LOG_COOKIE", page_text="DO_NOT_LOG_PAGE",
        )
        main._retrieval_event(
            "search_error", endpoint="DO_NOT_LOG_ENDPOINT", reason="DO_NOT_LOG_REASON",
            error_type="DO_NOT_LOG_EXCEPTION",
        )
        self.logger.error("DO_NOT_LOG_UNSTRUCTURED_MESSAGE")
        # Normal application logs are not attached to this file handler.
        with patch.object(main.logger, "propagate", False):
            main.logger.info("DO_NOT_LOG_NORMAL_APP_QUERY")
        text = self.read_log()
        self.assertIn('"endpoint": "HTML POST"', text)
        self.assertIn('"reason": "tls"', text)
        self.assertIn('"error_type": "SSLError"', text)
        self.assertIn('"error_type": "OtherError"', text)
        self.assertNotIn("DO_NOT_LOG", text)
        self.assertNotIn("private.test", text)

    def test_tls_proxy_timeout_and_connection_errors_are_distinguished(self):
        for error, reason in (
            (main.requests.exceptions.SSLError("DO_NOT_LOG_TLS_DETAIL"), "tls"),
            (main.requests.exceptions.ProxyError("DO_NOT_LOG_PROXY_DETAIL"), "proxy"),
            (main.requests.exceptions.Timeout("DO_NOT_LOG_TIMEOUT_DETAIL"), "timeout"),
            (main.requests.exceptions.ConnectionError("DO_NOT_LOG_CONNECTION_DETAIL"), "connection"),
        ):
            self.assertEqual(main._retrieval_error_reason(error), reason)
            with patch.object(main.requests, "post", side_effect=error), \
                 patch.object(main.requests, "get", side_effect=error):
                self.assertEqual(main.fetch_duckduckgo_web("DO_NOT_LOG_QUERY"), ([], []))
        text = self.read_log()
        for reason in ("tls", "proxy", "timeout", "connection"):
            self.assertIn(f'"reason": "{reason}"', text)
        self.assertNotIn("DO_NOT_LOG", text)
        self.assertIn("search_complete", text)

    def test_attempted_news_retry_is_logged_even_when_it_produces_no_evidence(self):
        with patch.object(main, "fetch_duckduckgo_web", return_value=([], [])), \
             patch.object(main, "fetch_wikipedia", return_value=("", "")):
            self.assertEqual(main.search_and_scrape("DO_NOT_LOG_QUERY", "news"), ("", []))
        text = self.read_log()
        self.assertIn('"retried": true', text)
        self.assertIn('"sources": 0', text)
        self.assertNotIn("DO_NOT_LOG", text)

    def test_logging_setup_is_idempotent_and_rotation_is_bounded(self):
        diagnostics.configure_diagnostics(Path(self.directory.name))
        self.assertEqual(len(self.logger.handlers), 1)
        handler = self.logger.handlers[0]
        self.assertEqual(handler.maxBytes, 512 * 1024)
        self.assertEqual(handler.backupCount, 2)
        handler.maxBytes = 180
        for _ in range(30):
            main._retrieval_event("search_http", endpoint="HTML POST", status=202)
        files = list(Path(self.directory.name).glob("retrieval.log*"))
        self.assertEqual(len(files), 3)

    def test_actual_loaded_runtime_is_fingerprinted_without_logging_its_path(self):
        directory = Path(self.directory.name) / "DO_NOT_LOG_USER_PATH"
        directory.mkdir()
        runtime = directory / "main.pyc"
        runtime.write_bytes(b"compiled runtime fixture")
        diagnostics.record_runtime(directory)
        text = self.read_log()
        self.assertIn('"runtime_format": "bytecode"', text)
        self.assertIn(hashlib.sha256(runtime.read_bytes()).hexdigest(), text)
        self.assertNotIn("DO_NOT_LOG", text)

    def test_windows_logging_is_initialized_before_loading_the_site(self):
        source = (ROOT / "windows_release/run_windows.py").read_text(encoding="utf-8")
        start = source.index("def main()")
        source = source[start:]
        self.assertLess(source.index("configure_diagnostics()"), source.index("load_site_app("))
        self.assertLess(source.index("record_runtime("), source.index("load_site_app("))
        export = (ROOT / "windows_release/tools/export_build_source.py").read_text(encoding="utf-8")
        self.assertIn('"windows_release/poinsettia_windows/diagnostics.py"', export)