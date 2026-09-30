import base64
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Response

import main


class MultimodalMessageTests(unittest.TestCase):
    def setUp(self):
        main.app.config.update(TESTING=True, SECRET_KEY="multimodal-test-secret")
        self.client = main.app.test_client()
        self.authenticated_user = {
            "id": 42,
            "eula_update_required": False,
            "privacy_update_required": False,
        }

    def test_normalizes_image_and_audio_aliases_for_ollama(self):
        normalized = main.prepare_ollama_messages(
            [
                {"role": "system", "content": "Be helpful."},
                {
                    "role": "user",
                    "content": "Describe these.",
                    "images": ["aW1hZ2U="],
                    "audio": [{"data": "UklGRg=="}],
                    "attachments": [{"name": "private-ui-metadata"}],
                },
            ]
        )

        self.assertEqual(normalized[-1]["images"], ["aW1hZ2U=", "UklGRg=="])
        self.assertNotIn("audio", normalized[-1])
        self.assertNotIn("attachments", normalized[-1])

    def test_rejects_non_base64_attachment_values(self):
        with self.assertRaisesRegex(ValueError, "base64"):
            main.prepare_ollama_messages(
                [{"role": "user", "content": "inspect", "images": [None]}]
            )

    def test_rejects_oversized_attachment(self):
        with patch.object(main, "MAX_MULTIMODAL_ITEM_CHARS", 8):
            with self.assertRaisesRegex(ValueError, "too large"):
                main.prepare_ollama_messages(
                    [{"role": "user", "content": "inspect", "images": ["123456789"]}]
                )

    def test_chat_route_rejects_invalid_attachment(self):
        with patch.object(main, "get_current_user", return_value=self.authenticated_user):
            response = self.client.post(
                "/chat/stream",
                json={
                    "mode": "p2",
                    "messages": [
                        {"role": "user", "content": "inspect", "images": [None]}
                    ],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("base64", response.json["error"])

    def test_chat_route_rejects_oversized_attachment(self):
        with patch.object(main, "MAX_MULTIMODAL_ITEM_CHARS", 8):
            with patch.object(
                main, "get_current_user", return_value=self.authenticated_user
            ):
                response = self.client.post(
                    "/chat/stream",
                    json={
                        "mode": "p2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "inspect",
                                "images": ["123456789"],
                            }
                        ],
                    },
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json["error"])

    def test_chat_route_forwards_normalized_media(self):
        with patch.object(main, "get_current_user", return_value=self.authenticated_user):
            with patch.object(main, "stream_p2", return_value=Response("ok")) as stream:
                response = self.client.post(
                    "/chat/stream",
                    json={
                        "mode": "p2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "inspect",
                                "images": ["aW1hZ2U="],
                                "audio": ["UklGRg=="],
                                "attachments": [{"name": "ignored"}],
                            }
                        ],
                    },
                )

        self.assertEqual(response.status_code, 200)
        forwarded_messages = stream.call_args.args[0]
        self.assertEqual(
            forwarded_messages[0]["images"], ["aW1hZ2U=", "UklGRg=="]
        )
        self.assertNotIn("attachments", forwarded_messages[0])

    def test_p2_images_use_p3_evidence_then_p2_answer_without_raw_images(self):
        wav = base64.b64encode(b'RIFF\x24\x00\x00\x00WAVE').decode()
        for media in (["aW1hZ2U="], ["aW1hZ2U=", wav]):
            with self.subTest(media=media):
                observation = MagicMock(status_code=200)
                observation.json.return_value = {
                    "message": {"content": "A robot points toward soldiers on a beach."}
                }
                model_response = MagicMock(status_code=200)
                model_response.__enter__.return_value = model_response
                model_response.iter_lines.return_value = [
                    json.dumps({"message": {"content": "A robot and soldiers."}, "done": True}).encode()
                ]
                with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
                     patch.object(main.requests, "post",
                                  side_effect=[observation, model_response]) as post:
                    response = self.client.post("/chat/stream", json={
                        "mode": "p2", "messages": [
                            {"role": "user", "content": "What is in this image?", "images": media},
                        ],
                    })
                    events = [
                        json.loads(line[6:])
                        for line in response.get_data(as_text=True).splitlines()
                        if line.startswith("data: ")
                    ]
                self.assertEqual(post.call_count, 2)
                vision = post.call_args_list[0].kwargs["json"]
                answer = post.call_args_list[1].kwargs["json"]
                self.assertEqual(vision["model"], main.P3_MODEL)
                self.assertEqual(vision["messages"][-1]["images"], ["aW1hZ2U="])
                self.assertIs(vision["think"], False)
                self.assertEqual(answer["model"], "poinsettia")
                self.assertIn("A robot points", answer["messages"][-1]["content"])
                self.assertEqual(answer["messages"][-1].get("images", []), [wav] if len(media) > 1 else [])
                self.assertEqual(
                    "".join(event.get("text", "") for event in events),
                    "Poinsettia 3 inspected the image for this Poinsettia 2 answer.\n\nA robot and soldiers.",
                )
                self.assertFalse(any("error" in event for event in events))
                self.assertTrue(any(event.get("done") for event in events))

    def test_p2_audio_and_text_only_do_not_invoke_p3_vision(self):
        wav = base64.b64encode(b'RIFF\x24\x00\x00\x00WAVE').decode()
        for message in (
            {"role": "user", "content": "What did they say?", "audio": [wav]},
            {"role": "user", "content": "Hello"},
        ):
            with self.subTest(message=message):
                model_response = MagicMock(status_code=200)
                model_response.__enter__.return_value = model_response
                model_response.iter_lines.return_value = [
                    json.dumps({"message": {"content": "Hello."}, "done": True}).encode()
                ]
                with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
                     patch.object(main, "generate_commands", return_value=([], None)), \
                     patch.object(main.requests, "post", return_value=model_response) as post:
                    response = self.client.post("/chat/stream", json={
                        "mode": "p2", "messages": [message],
                    })
                    response.get_data()
                self.assertEqual(post.call_count, 1)
                request = post.call_args.kwargs["json"]
                self.assertEqual(request["model"], "poinsettia")
                self.assertEqual(request["messages"][-1].get("images", []),
                                 [wav] if "audio" in message else [])

    def test_p2_image_fails_closed_if_p3_cannot_observe_it(self):
        failure = MagicMock(status_code=400)
        failure.json.return_value = {"error": {"message": "Image processing unavailable"}}
        with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
             patch.object(main.requests, "post", return_value=failure) as post:
            response = self.client.post("/chat/stream", json={
                "mode": "p2", "messages": [
                    {"role": "user", "content": "Describe this image", "images": ["aW1hZ2U="]},
                ],
            })
            events = [
                json.loads(line[6:])
                for line in response.get_data(as_text=True).splitlines()
                if line.startswith("data: ")
            ]
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["model"], main.P3_MODEL)
        self.assertTrue(any("P3 could not inspect" in event.get("error", "") for event in events))
        self.assertFalse(any(event.get("done") for event in events))

    def test_p2_image_fails_closed_if_p3_says_no_visual_content(self):
        observation = MagicMock(status_code=200)
        observation.json.return_value = {
            "message": {"content": "No visual content was provided for me to analyze."}
        }
        with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
             patch.object(main.requests, "post", return_value=observation) as post:
            response = self.client.post("/chat/stream", json={
                "mode": "p2", "messages": [
                    {"role": "user", "content": "Describe this image", "images": ["aW1hZ2U="]},
                ],
            })
            events = [
                json.loads(line[6:])
                for line in response.get_data(as_text=True).splitlines()
                if line.startswith("data: ")
            ]
        self.assertEqual(post.call_count, 1)
        self.assertTrue(any("did not return a usable image" in event.get("error", "")
                            for event in events))
        self.assertFalse(any(event.get("done") for event in events))

    def test_p3_simple_image_question_does_not_wait_for_web_search(self):
        model_response = MagicMock(status_code=200)
        model_response.__enter__.return_value = model_response
        model_response.iter_lines.return_value = [
            json.dumps({"message": {"content": "A painting."}, "done": True}).encode()
        ]
        with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
             patch.object(main, "search_and_scrape") as search, \
             patch.object(main.requests, "post", return_value=model_response) as post:
            response = self.client.post("/chat/stream", json={
                "mode": "p3", "messages": [
                    {"role": "user", "content": "What is in this image?", "images": ["aW1hZ2U="]},
                ],
            })
            response.get_data()
        search.assert_not_called()
        self.assertEqual(post.call_args.kwargs["json"]["model"], main.P3_MODEL)
        self.assertEqual(post.call_args.kwargs["json"]["messages"][-1]["images"], ["aW1hZ2U="])

    def test_simple_image_question_skips_web_but_current_image_facts_search(self):
        image = ["aW1hZ2U="]
        self.assertEqual(
            main.generate_commands([{"role": "user", "content": "What is in this image?", "images": image}]),
            ([], None),
        )
        query = "What is the current price of the item in this image?"
        self.assertEqual(
            main.generate_commands([{"role": "user", "content": query, "images": image}]),
            ([query], None),
        )
        historical = "What is the history of the monument in this picture?"
        self.assertEqual(
            main.generate_commands([{"role": "user", "content": historical, "images": image}]),
            ([historical], None),
        )
        self.assertEqual(
            main.generate_commands([{"role": "user", "content": "What did they say?",
                                     "images": [base64.b64encode(b'RIFF\x24\x00\x00\x00WAVE').decode()]}]),
            ([], None),
        )

    def test_p2_reports_model_rejection_without_dumping_raw_json(self):
        failure = MagicMock(status_code=400)
        failure.__enter__.return_value = failure
        failure.json.return_value = {
            "error": {
                "code": 400,
                "message": "Multimodal data provided, but model does not support multimodal requests.",
            }
        }
        with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
             patch.object(main, "generate_commands", return_value=([], None)), \
             patch.object(main.requests, "post", return_value=failure):
            response = self.client.post("/chat/stream", json={
                "mode": "p2", "messages": [
                    {"role": "user", "content": "Transcribe this audio",
                     "audio": [base64.b64encode(b'RIFF\x24\x00\x00\x00WAVE').decode()]},
                ],
            })
            events = [
                json.loads(line[6:])
                for line in response.get_data(as_text=True).splitlines()
                if line.startswith("data: ")
            ]

        errors = [event["error"] for event in events if "error" in event]
        self.assertEqual(len(errors), 1)
        self.assertIn("Multimodal data provided", errors[0])
        self.assertNotIn('{"error":', errors[0])
        self.assertFalse(any(event.get("done") for event in events))

    def test_p2_model_and_windows_bootstrap_use_e4b(self):
        root = Path(main.__file__).resolve().parent
        self.assertTrue((root / "Modelfile").read_text().startswith("FROM gemma4:e4b\n"))
        self.assertIn(
            'Base = "gemma4:e4b"; Name = "poinsettia"',
            (root / "start_poinsettia.ps1").read_text(),
        )

    def test_p4_rejects_audio_attachments(self):
        with patch.object(main, "get_current_user", return_value=self.authenticated_user):
            with patch.object(main, "mode_is_available", return_value=True):
                response = self.client.post(
                    "/chat/stream",
                    json={
                        "mode": main.P4_FAX_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": "inspect",
                                "audio": ["UklGRg=="],
                                "attachments": [{"kind": "audio", "name": "voice.wav"}],
                            }
                        ],
                    },
                )

        self.assertEqual(response.status_code, 400)
        self.assertIn("image attachments", response.json["error"])

    def test_p4_forwards_images_to_selected_variant(self):
        with patch.object(main, "get_current_user", return_value=self.authenticated_user):
            with patch.object(main, "mode_is_available", return_value=True):
                with patch.object(main, "stream_p4", return_value=Response("ok")) as stream:
                    response = self.client.post(
                        "/chat/stream",
                        json={
                            "mode": main.P4_CANDOR_MODEL,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "inspect",
                                    "images": ["aW1hZ2U="],
                                    "attachments": [{"kind": "image", "name": "photo.png"}],
                                }
                            ],
                        },
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(stream.call_args.args[0], main.P4_CANDOR_MODEL)
        forwarded_messages = stream.call_args.args[1]
        self.assertEqual(forwarded_messages[0]["images"], ["aW1hZ2U="])
        self.assertEqual(forwarded_messages[0]["role"], "user")

    def test_p4_is_immediately_available_in_catalog(self):
        self.assertTrue(main.p4_is_released())
        self.assertTrue(main.mode_is_available(main.P4_FAX_MODEL))
        self.assertTrue(main.mode_is_available(main.P4_CANDOR_MODEL))
        catalog = {
            item["mode"]: item
            for item in main.client_model_catalog()
            if item["mode"] in main.P4_MODES
        }
        self.assertEqual(set(catalog), set(main.P4_MODES))
        self.assertTrue(all(item["status"] == "released" for item in catalog.values()))

    def test_p4_uses_shared_research_and_file_pipeline(self):
        with patch.object(main, "stream_research_model", return_value="stream") as stream:
            result = main.stream_p4(
                main.P4_FAX_MODEL,
                [{"role": "user", "content": "research this and make a file"}],
                client_date="Monday, September 7, 2026",
            )

        self.assertEqual(result, "stream")
        stream.assert_called_once_with(
            main.P4_FAX_MODEL,
            "Poinsettia 4.0 “Fax”",
            [{"role": "user", "content": "research this and make a file"}],
            client_date="Monday, September 7, 2026",
            allow_audio=False,
        )


if __name__ == "__main__":
    unittest.main()