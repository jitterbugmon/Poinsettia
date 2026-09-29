import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import db
import main


class SearchPipelineTests(unittest.TestCase):
    def test_original_provider_order_and_citations(self):
        calls = []

        def wikipedia(query):
            calls.append("wikipedia")
            return "WIKIPEDIA"

        def instant(query):
            calls.append("instant")
            return "INSTANT"

        def web(query, domains=None):
            calls.append("web")
            return ["WEB"], ["https://source.test/page"]

        with patch.object(main, "fetch_wikipedia", side_effect=wikipedia), \
             patch.object(main, "fetch_duckduckgo_instant", side_effect=instant), \
             patch.object(main, "fetch_duckduckgo_web", side_effect=web):
            combined, urls = main.search_and_scrape("query", "science")

        self.assertEqual(calls, ["wikipedia", "instant", "web"])
        self.assertEqual(combined, "WIKIPEDIA\n\nINSTANT\n\nWEB")
        self.assertEqual(urls, ["https://source.test/page"])

    def test_web_scraping_falls_back_after_first_failure_and_preserves_sorted_sources(self):
        candidates = [
            "https://ordinary.test/article",
            "https://preferred.test/unavailable",
            "https://preferred.test/second",
            "https://last.test/article",
        ]
        html = "".join(f'<a class="result__a" href="{url}">result</a>' for url in candidates)
        response = type("Response", (), {"text": html})()

        call_order = []

        def scrape(url):
            call_order.append(url)
            if url.endswith("/unavailable"):
                return ""
            if url.endswith("/second"):
                return "SECOND RESULT"
            if url.endswith("/article"):
                return "ORDINARY RESULT"
            return ""

        with patch.object(main.requests, "post", return_value=response) as post:
            with patch.object(main, "scrape_url", side_effect=scrape):
                results, source_urls = main.fetch_duckduckgo_web(
                    "query", domains=["preferred.test"]
                )

        post.assert_called_once()
        self.assertEqual(call_order, [
            "https://preferred.test/unavailable",
            "https://preferred.test/second",
            "https://ordinary.test/article",
        ])
        self.assertEqual(
            source_urls,
            [
                "https://preferred.test/second",
                "https://ordinary.test/article",
            ],
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].endswith("\nSECOND RESULT"))
        self.assertTrue(results[1].endswith("\nORDINARY RESULT"))

    def test_p2_uses_the_shared_search_and_stream_pipeline(self):
        captured = []
        messages = [{"role": "user", "content": "recent discovery"}]

        def model_stream(model, prompt, **kwargs):
            captured.append((model, prompt))
            yield "answer", [], None

        with main.app.test_request_context("/"):
            with patch.object(main, "generate_commands", return_value=(["recent discovery"], None)), \
                 patch.object(main, "get_current_user", return_value=None), \
                 patch.object(main, "quick_classify", return_value="science"), \
                 patch.object(main, "search_and_scrape", return_value=("verified facts", ["https://source.test/page"])) as search, \
                 patch.object(main, "ollama_p3_stream", side_effect=model_stream), \
                 patch.object(main, "make_stream_response", side_effect=lambda generator: list(generator)):
                chunks = main.stream_p2(messages, client_date="Tuesday, September 29, 2026")

        search.assert_called_once_with("recent discovery", "science")
        self.assertEqual(captured[0][0], "poinsettia")
        self.assertIn("verified facts", captured[0][1][0]["content"])
        self.assertIn("Tuesday, September 29, 2026", captured[0][1][0]["content"])
        self.assertTrue(any('"sources": ["https://source.test/page"]' in chunk for chunk in chunks))
        self.assertTrue(any('"text": "answer"' in chunk for chunk in chunks))
        self.assertTrue(any('"done": true' in chunk for chunk in chunks))

    def test_p2_creates_a_downloadable_file_from_streamed_model_output(self):
        chunks = [
            {"message": {"content": "Here is your file:\n<<<FILE:notes.txt>>>\nFirst "}},
            {"message": {"content": "line\n<<<ENDFILE>>> All set."}},
            {"done": True},
        ]
        ollama_response = MagicMock()
        ollama_response.status_code = 200
        ollama_response.__enter__.return_value = ollama_response
        ollama_response.iter_lines.return_value = [
            json.dumps(chunk).encode("utf-8") for chunk in chunks
        ]

        with tempfile.TemporaryDirectory() as directory:
            database_path = os.path.join(directory, "test.db")
            with patch.object(db, "DB_PATH", database_path), \
                 patch.object(main, "_file_dir", return_value=directory), \
                 patch.object(main, "require_authenticated_user", return_value=None), \
                 patch.object(main, "get_current_user", return_value=None), \
                 patch.object(main, "generate_commands", return_value=([], None)), \
                 patch.object(main.requests, "post", return_value=ollama_response) as post:
                db.init_db()
                client = main.app.test_client()
                response = client.post(
                    "/chat/stream",
                    json={
                        "mode": "p2",
                        "messages": [{"role": "user", "content": "Create a notes.txt file"}],
                    },
                )
                events = [
                    json.loads(line[6:])
                    for line in response.get_data(as_text=True).splitlines()
                    if line.startswith("data: ")
                ]
                with client.session_transaction() as session:
                    guest_key = session["guest_key"]
                conn = db.get_db()
                saved = conn.execute(
                    "SELECT name, path, session_key FROM files"
                ).fetchone()
                conn.close()
                self.assertEqual(response.status_code, 200)
                self.assertIsNotNone(saved)
                self.assertEqual(saved["name"], "notes.txt")
                self.assertEqual(saved["session_key"], guest_key)
                with open(saved["path"], encoding="utf-8") as created:
                    self.assertEqual(created.read(), "First line")

        self.assertEqual(post.call_args.kwargs["json"]["model"], "poinsettia")
        self.assertTrue(any(event.get("file", {}).get("name") == "notes.txt" for event in events))
        self.assertTrue(any(event.get("done") for event in events))
        self.assertNotIn("<<<FILE:", "".join(event.get("text", "") for event in events))

    def test_research_stream_does_not_require_internet_preflight_for_mocked_retrieval(self):
        with main.app.test_request_context("/"):
            with patch.object(
                main, "check_internet", side_effect=AssertionError("preflight called"),
                create=True
            ) as check_internet:
                with patch.object(main, "generate_commands", return_value=(["query"], None)):
                    with patch.object(main, "get_current_user", return_value=None):
                        with patch.object(
                            main, "search_and_scrape", return_value=("mock context", [])
                        ):
                            with patch.object(main, "quick_classify", return_value="general"):
                                with patch.object(
                                    main,
                                    "ollama_p3_stream",
                                    return_value=iter([("answer", [], None)]),
                                ):
                                    with patch.object(
                                        main,
                                        "make_stream_response",
                                        side_effect=lambda generator: list(generator),
                                    ):
                                        chunks = main.stream_research_model(
                                            "model",
                                            "Research model",
                                            [{"role": "user", "content": "query"}],
                                        )

        check_internet.assert_not_called()
        self.assertTrue(any('"text": "answer"' in chunk for chunk in chunks))


if __name__ == "__main__":
    unittest.main()