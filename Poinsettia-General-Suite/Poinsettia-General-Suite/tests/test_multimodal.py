import unittest
from unittest.mock import patch

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