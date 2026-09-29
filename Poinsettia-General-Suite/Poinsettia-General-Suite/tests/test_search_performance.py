import threading
import unittest
from unittest.mock import patch

import main


class SearchPerformanceRegressionTests(unittest.TestCase):
    def test_independent_searches_run_concurrently_and_keep_output_order(self):
        rendezvous = threading.Barrier(3, timeout=3)
        web_finished = threading.Event()

        def arrive():
            rendezvous.wait()

        def wikipedia(query):
            arrive()
            self.assertTrue(web_finished.wait(3), "web search did not finish")
            return "WIKIPEDIA"

        def instant(query):
            arrive()
            self.assertTrue(web_finished.wait(3), "web search did not finish")
            return "INSTANT"

        def web(query, domains=None):
            arrive()
            web_finished.set()
            return ["WEB"], ["https://source.test/page"]

        with patch.object(main, "fetch_wikipedia", side_effect=wikipedia):
            with patch.object(main, "fetch_duckduckgo_instant", side_effect=instant):
                with patch.object(main, "fetch_duckduckgo_web", side_effect=web):
                    combined, urls = main.search_and_scrape("query", "science")

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

        first_pair = threading.Barrier(2, timeout=3)
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0
        call_order = []

        def scrape(url):
            nonlocal active, maximum_active
            with state_lock:
                call_order.append(url)
                ordinal = len(call_order)
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                if ordinal <= 2:
                    first_pair.wait()
                if url.endswith("/unavailable"):
                    return ""
                if url.endswith("/second"):
                    return "SECOND RESULT"
                if url.endswith("/article"):
                    return "ORDINARY RESULT"
                return ""
            finally:
                with state_lock:
                    active -= 1

        with patch.object(main.requests, "post", return_value=response) as post:
            with patch.object(main, "scrape_url", side_effect=scrape):
                results, source_urls = main.fetch_duckduckgo_web(
                    "query", domains=["preferred.test"]
                )

        post.assert_called_once()
        self.assertEqual(
            set(call_order[:2]),
            {
                "https://preferred.test/unavailable",
                "https://preferred.test/second",
            },
        )
        self.assertLessEqual(maximum_active, 2)
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