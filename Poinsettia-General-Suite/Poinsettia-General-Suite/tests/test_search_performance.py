import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import db
import main


class SearchPipelineTests(unittest.TestCase):
    def test_requested_source_categories_and_domain_filters(self):
        self.assertEqual(main.quick_classify("What is IMDb's rating for this movie?"), "entertainment")
        self.assertEqual(main.quick_classify("Buy an Adafruit board on Amazon"), "shopping")
        self.assertEqual(main.quick_classify("Amazon Adafruit Feather RP2040 price"), "shopping")
        self.assertEqual(main.quick_classify("What is the stock price?"), "finance")
        self.assertEqual(main.quick_classify("What is Hacker News saying about software?"), "technology")
        self.assertIn("imdb.com", main.CATEGORY_SOURCES["entertainment"]["domains"])
        self.assertIn("adafruit.com", main.CATEGORY_SOURCES["technology"]["domains"])
        self.assertIn("amazon.com", main.CATEGORY_SOURCES["shopping"]["domains"])
        self.assertIn("news.ycombinator.com", main.CATEGORY_SOURCES["technology"]["domains"])
        self.assertIn("reddit.com", main.CATEGORY_SOURCES["general"]["domains"])
        self.assertTrue(main._domain_matches("https://www.amazon.com/dp/example", "amazon.com"))
        self.assertFalse(main._domain_matches("https://notamazon.com/dp/example", "amazon.com"))
        self.assertNotIn("amazon.com", main._JUNK_DOMAINS)
        self.assertNotIn("reddit.com", main._JUNK_DOMAINS)

    def test_original_provider_order_and_citations(self):
        calls = []

        def wikipedia(query):
            calls.append("wikipedia")
            return "WIKIPEDIA", "https://wiki.test/page"

        def instant(query):
            calls.append("instant")
            return "INSTANT", "https://instant.test/page"

        def web(query, domains=None):
            calls.append("web")
            return ["WEB"], ["https://source.test/page"]

        with patch.object(main, "fetch_wikipedia", side_effect=wikipedia), \
             patch.object(main, "fetch_duckduckgo_instant", side_effect=instant), \
             patch.object(main, "fetch_duckduckgo_web", side_effect=web):
            combined, urls = main.search_and_scrape("query", "science")

        self.assertEqual(calls, ["wikipedia", "instant", "web"])
        self.assertEqual(combined, "WIKIPEDIA\n\nINSTANT\n\nWEB")
        self.assertEqual(urls, [
            "https://wiki.test/page",
            "https://instant.test/page",
            "https://source.test/page",
        ])

    def test_wikipedia_quoted_movie_search_rejects_unrelated_top_hit(self):
        search_response = MagicMock()
        search_response.json.return_value = {
            "query": {"search": [
                {"title": "John Schneider (screen actor)"},
                {"title": "The Odyssey (2026 film)"},
            ]}
        }
        summary_response = MagicMock()
        summary_response.json.return_value = {
            "extract": "A film adaptation of the epic.",
            "content_urls": {
                "desktop": {"page": "https://en.wikipedia.org/wiki/The_Odyssey_(2026_film)"}
            },
        }
        with patch.object(main.requests, "get", side_effect=[search_response, summary_response]) as get:
            text, url = main.fetch_wikipedia('What is the movie "The Odyssey" about?')

        self.assertEqual(get.call_args_list[0].kwargs["params"]["srsearch"], "The Odyssey film")
        self.assertIn("The_Odyssey_(2026_film)", get.call_args_list[1].args[0])
        self.assertIn("A film adaptation", text)
        self.assertEqual(url, "https://en.wikipedia.org/wiki/The_Odyssey_(2026_film)")

    def test_wikipedia_does_not_use_an_unrelated_result(self):
        response = MagicMock()
        response.json.return_value = {
            "query": {"search": [{"title": "John Schneider (screen actor)"}]}
        }
        with patch.object(main.requests, "get", return_value=response) as get:
            self.assertEqual(
                main.fetch_wikipedia('What is the movie "The Odyssey" about?'),
                ("", ""),
            )
        get.assert_called_once()

    def test_wikipedia_source_is_emitted_when_html_search_is_empty(self):
        with patch.object(
            main, "fetch_wikipedia",
            return_value=("[Wikipedia — The Odyssey (2026 film)]\nFilm summary",
                          "https://en.wikipedia.org/wiki/The_Odyssey_(2026_film)"),
        ), patch.object(
            main, "fetch_duckduckgo_instant", return_value=("", "")
        ), patch.object(
            main, "fetch_duckduckgo_web", return_value=([], [])
        ):
            context, urls = main.search_and_scrape('What is the movie "The Odyssey" about?', 'entertainment')

        self.assertIn("Film summary", context)
        self.assertEqual(urls, ["https://en.wikipedia.org/wiki/The_Odyssey_(2026_film)"])

    def test_web_scraping_falls_back_after_first_failure_and_preserves_sorted_sources(self):
        candidates = [
            "https://ordinary.test/article",
            "https://preferred.test/unavailable",
            "https://preferred.test/second",
            "https://last.test/article",
        ]
        html = "".join(f'<a class="result__a" href="{url}">result</a>' for url in candidates)
        response = type("Response", (), {"text": html, "status_code": 200})()

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

    def test_html_get_fallback_runs_when_post_has_no_results(self):
        empty_post = type("Response", (), {"text": "", "status_code": 200})()
        get_result = type("Response", (), {
            "text": '<a class="result__a" href="https://film.test/odyssey">Film</a>',
            "status_code": 200,
        })()
        with patch.object(main.requests, "post", return_value=empty_post) as post, \
             patch.object(main.requests, "get", return_value=get_result) as get, \
             patch.object(main, "scrape_url", return_value="Film synopsis") as scrape:
            results, urls = main.fetch_duckduckgo_web("The Odyssey film")

        post.assert_called_once()
        get.assert_called_once()
        scrape.assert_called_once_with("https://film.test/odyssey")
        self.assertEqual(urls, ["https://film.test/odyssey"])
        self.assertIn("Film synopsis", results[0])

    def test_blocked_imdb_page_uses_labeled_snippet_and_citation(self):
        html = '''
        <div class="result__body">
            <a class="result__a" href="https://www.imdb.com/title/tt123/">IMDb film</a>
            <a class="result__snippet">A film following an ancient voyage home
            with many dangerous encounters along the way.</a>
        </div>
        '''
        response = type("Response", (), {"text": html, "status_code": 200})()
        with patch.object(main.requests, "post", return_value=response), \
             patch.object(main, "scrape_url", return_value="") as scrape:
            pages, urls = main.fetch_duckduckgo_web(
                "The Odyssey IMDb", domains=main.CATEGORY_SOURCES["entertainment"]["domains"]
            )

        scrape.assert_called_once_with("https://www.imdb.com/title/tt123/")
        self.assertEqual(urls, ["https://www.imdb.com/title/tt123/"])
        self.assertIn("Search-result snippet (full page unavailable)", pages[0])
        self.assertIn("dangerous encounters", pages[0])

    def test_amazon_result_is_eligible_for_shopping_and_uses_labeled_snippet(self):
        html = '''
        <div class="result__body">
            <a class="result__a" href="https://www.amazon.com/dp/B123">Product</a>
            <a class="result__snippet">A board listing with the features and
            specifications of the Adafruit Feather RP2040 microcontroller.</a>
        </div>
        '''
        response = type("Response", (), {"text": html, "status_code": 200})()
        with patch.object(main.requests, "post", return_value=response), \
             patch.object(main, "scrape_url", return_value=""):
            pages, urls = main.fetch_duckduckgo_web(
                "Amazon Adafruit Feather RP2040 price",
                domains=main.CATEGORY_SOURCES["shopping"]["domains"],
            )

        self.assertEqual(urls, ["https://www.amazon.com/dp/B123"])
        self.assertIn("Search-result snippet (full page unavailable)", pages[0])

    def test_second_blocked_imdb_snippet_does_not_hide_other_site(self):
        imdb_snippet = ("An adventure film about a voyage home with an "
                        "ensemble cast and mythical encounters.")
        html = f'''
        <div class="result__body">
            <a class="result__a" href="https://www.imdb.com/title/first">Film A</a>
            <a class="result__snippet">{imdb_snippet}</a>
        </div>
        <div class="result__body">
            <a class="result__a" href="https://www.imdb.com/title/second">Film B</a>
            <a class="result__snippet">{imdb_snippet}</a>
        </div>
        <div class="result__body">
            <a class="result__a" href="https://www.rottentomatoes.com/m/first">Film A reviews</a>
        </div>
        '''
        response = type("Response", (), {"text": html, "status_code": 200})()
        def scrape(url):
            return "Film A review page" if "rottentomatoes" in url else ""

        with patch.object(main.requests, "post", return_value=response), \
             patch.object(main, "scrape_url", side_effect=scrape):
            pages, urls = main.fetch_duckduckgo_web(
                "The Odyssey IMDb", domains=main.CATEGORY_SOURCES["entertainment"]["domains"]
            )

        self.assertEqual(urls, [
            "https://www.imdb.com/title/first",
            "https://www.rottentomatoes.com/m/first",
        ])
        self.assertIn("Search-result snippet", pages[0])

    def test_named_reddit_source_beats_other_preferred_technology_results(self):
        html = '''
        <div class="result__body">
            <a class="result__a" href="https://developer.mozilla.org/en-US/docs/Web/API">Docs</a>
        </div>
        <div class="result__body">
            <a class="result__a" href="https://www.reddit.com/r/webdev/comments/example">Discussion</a>
        </div>
        '''
        response = type("Response", (), {"text": html, "status_code": 200})()
        with patch.object(main.requests, "post", return_value=response), \
             patch.object(main, "scrape_url", return_value="Useful discussion") as scrape:
            _, urls = main.fetch_duckduckgo_web(
                "What do Reddit users think about this web API?",
                domains=main.CATEGORY_SOURCES["technology"]["domains"],
            )

        self.assertEqual(urls[0], "https://www.reddit.com/r/webdev/comments/example")
        self.assertEqual(scrape.call_count, 2)

    def test_blocked_page_is_not_used_as_a_scraped_source(self):
        response = type("Response", (), {"text": "Bot challenge", "status_code": 202})()
        with patch.object(main.requests, "get", return_value=response):
            self.assertEqual(main.scrape_url("https://www.imdb.com/title/example"), "")

    def test_wikipedia_does_not_crowd_out_two_web_sources(self):
        with patch.object(
            main, "fetch_wikipedia",
            return_value=("[Wikipedia — Film]\n" + "W" * 1500, "https://wiki.test/film"),
        ), patch.object(
            main, "fetch_duckduckgo_instant", return_value=("", "")
        ), patch.object(
            main, "fetch_duckduckgo_web",
            return_value=([
                "[imdb.com — https://www.imdb.com/title/film]\n" + "I" * 1000,
                "[reddit.com — https://www.reddit.com/r/film]\n" + "R" * 1000,
            ], ["https://www.imdb.com/title/film", "https://www.reddit.com/r/film"]),
        ):
            context, urls = main.search_and_scrape("What is the movie about?", "entertainment")

        self.assertLessEqual(len(context), 2000)
        self.assertIn("I" * 50, context)
        self.assertIn("R" * 50, context)
        self.assertEqual(len(urls), 3)

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
        self.assertIn("Do not say you cannot search", captured[0][1][0]["content"])
        self.assertNotIn("Web search returned no usable results", captured[0][1][0]["content"])
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