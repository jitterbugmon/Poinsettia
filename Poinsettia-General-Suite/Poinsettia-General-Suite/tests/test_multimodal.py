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

    def test_p2_sends_image_and_audio_directly_to_poinsettia(self):
        for attachment_field, payload in (
            ("images", "aW1hZ2U="),
            ("audio", "UklGRg=="),
        ):
            with self.subTest(attachment_field=attachment_field):
                model_response = MagicMock(status_code=200)
                model_response.__enter__.return_value = model_response
                model_response.iter_lines.return_value = [
                    json.dumps({"message": {"content": "Observed."}, "done": True}).encode()
                ]
                with patch.object(main, "get_current_user", return_value=self.authenticated_user), \
                     patch.object(main, "generate_commands", return_value=([], None)), \
                     patch.object(main.requests, "post", return_value=model_response) as post:
                    response = self.client.post("/chat/stream", json={
                        "mode": "p2", "messages": [
                            {"role": "user", "content": "What is attached?",
                             attachment_field: [payload]},
                        ],
                    })
                    events = [
                        json.loads(line[6:])
                        for line in response.get_data(as_text=True).splitlines()
                        if line.startswith("data: ")
                    ]

                self.assertEqual(post.call_count, 1)
                request = post.call_args.kwargs["json"]
                self.assertEqual(request["model"], "poinsettia")
                self.assertEqual(request["messages"][-1]["images"], [payload])
                self.assertEqual(
                    "".join(event.get("text", "") for event in events), "Observed."
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
                    {"role": "user", "content": "Describe this", "images": ["aW1hZ2U="]},
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