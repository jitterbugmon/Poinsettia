import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "windows_release"))

from poinsettia_windows.ollama import OllamaManager


class OllamaProgressTests(unittest.TestCase):
    def test_pull_handles_missing_completed_value(self):
        response = Mock()
        response.iter_lines.return_value = [
            json.dumps({"status": "starting", "completed": None, "total": 100}),
            json.dumps({"status": "downloading", "completed": 50, "total": 100}),
        ]
        manager = OllamaManager()

        with patch("poinsettia_windows.ollama.requests.post", return_value=response):
            manager._pull("test-model", 20, 60)

        self.assertEqual(manager.snapshot()["percent"], 40)
        response.raise_for_status.assert_called_once()

    def test_pull_handles_missing_or_invalid_progress_totals(self):
        response = Mock()
        response.iter_lines.return_value = [
            json.dumps({"status": "starting", "completed": 10}),
            json.dumps({"status": "downloading", "completed": 10, "total": None}),
        ]
        manager = OllamaManager()

        with patch("poinsettia_windows.ollama.requests.post", return_value=response):
            manager._pull("test-model", 20, 60)

        self.assertEqual(manager.snapshot()["percent"], 20)


if __name__ == "__main__":
    unittest.main()
