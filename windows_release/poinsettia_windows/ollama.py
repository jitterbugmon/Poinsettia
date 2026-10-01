from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import requests

from .config import (
    OLLAMA_URL,
    P2_BASE_MODEL,
    P2_MODEL,
    P3_BASE_MODEL,
    P3_MODEL,
    P4_CANDOR_BASE_MODEL,
    P4_CANDOR_MODEL,
    P4_FAX_BASE_MODEL,
    P4_FAX_MODEL,
    MODEL_ROOT,
    OLLAMA_INSTALLER_SHA256,
    OLLAMA_INSTALLER_URL,
    SYSTEM_PROMPTS,
    local_data_root,
)


class OllamaManager:
    """Owns first-run Ollama/model setup and exposes safe UI progress."""

    def __init__(self) -> None:
        self.url = OLLAMA_URL.rstrip("/")
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "phase": "not_started",
            "percent": 0,
            "message": "Ready to check the local AI runtime.",
            "error": None,
            "ollama_available": False,
            "models": {},
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    def executable(self) -> str | None:
        candidates = [
            shutil.which("ollama"),
            os.environ.get("OLLAMA_EXE"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        ]
        return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)

    def probe(self) -> bool:
        try:
            response = requests.get(f"{self.url}/api/version", timeout=1.5)
            available = response.ok
        except requests.RequestException:
            available = False
        self._update(ollama_available=available)
        return available

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._bootstrap, name="poinsettia-bootstrap", daemon=True)
        self._thread.start()

    def _bootstrap(self) -> None:
        try:
            self._update(phase="checking", percent=2, message="Checking for the local AI runtime.", error=None)
            if not self.probe():
                self._update(phase="installing", percent=5, message="Installing Ollama from the official Windows package.")
                self._install_ollama()
                if not self._wait_for_ollama():
                    raise RuntimeError("Ollama did not become available after installation.")

            self._update(phase="models", percent=10, message="Preparing Poinsettia models.")
            self._ensure_model(P2_MODEL, P2_BASE_MODEL, MODEL_ROOT / "Modelfile.p2", 5, 25)
            self._ensure_model(P3_MODEL, P3_BASE_MODEL, MODEL_ROOT / "Modelfile.p3", 25, 50)
            self._ensure_model(P4_FAX_MODEL, P4_FAX_BASE_MODEL, MODEL_ROOT / "Modelfile.p4-fax", 50, 75)
            self._ensure_model(P4_CANDOR_MODEL, P4_CANDOR_BASE_MODEL, MODEL_ROOT / "Modelfile.p4-candor", 75, 100)
            self._update(phase="ready", percent=100, message="Poinsettia models are ready.", ollama_available=True)
        except Exception as exc:
            self._update(phase="error", message=str(exc), error=str(exc))

    def _wait_for_ollama(self, timeout: int = 180) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.probe():
                return True
            time.sleep(2)
        return False

    def _install_ollama(self) -> None:
        """Download, verify, and launch the official installer without UI noise."""
        if os.name != "nt":
            raise RuntimeError("Automatic Ollama installation is available only in the Windows release.")
        installer = local_data_root() / "OllamaSetup.exe"
        partial_installer = installer.with_suffix(".download")
        with requests.get(OLLAMA_INSTALLER_URL, stream=True, timeout=30) as response:
            response.raise_for_status()
            with partial_installer.open("wb") as destination:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        destination.write(chunk)
        partial_installer.replace(installer)
        self._verify_installer(installer)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen([str(installer), "/S"], creationflags=flags)
        if process.wait(timeout=300) != 0:
            raise RuntimeError("The official Ollama installer returned an error.")

    def _verify_installer(self, installer: Path) -> None:
        """Require a valid Windows signature and optionally a release hash pin."""
        expected_hash = OLLAMA_INSTALLER_SHA256
        if expected_hash:
            digest = hashlib.sha256()
            with installer.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != expected_hash:
                raise RuntimeError("The downloaded Ollama installer failed its SHA-256 integrity check.")

        signature_check = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    "$signature = Get-AuthenticodeSignature -LiteralPath "
                    f"'{installer}' ; if ($signature.Status -ne 'Valid') {{ exit 1 }}"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if signature_check.returncode != 0:
            raise RuntimeError("The downloaded Ollama installer does not have a valid Authenticode signature.")

    def _ensure_model(self, model: str, base: str, modelfile: Path, start: int, end: int) -> None:
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=3)
            installed = {item.get("name") for item in response.json().get("models", [])}
        except (requests.RequestException, ValueError):
            installed = set()

        if base not in installed and f"{base}:latest" not in installed:
            self._pull(base, start, start + max(1, int((end - start) * 0.72)))
        self._update(phase="creating", percent=max(start, end - 10), message=f"Creating {model}.")
        executable = self.executable()
        if not executable:
            raise RuntimeError("Ollama is running, but its command-line executable was not found.")
        result = subprocess.run(
            [executable, "create", model, "-f", str(modelfile)],
            capture_output=True,
            text=True,
            timeout=900,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Could not create {model}.")
        with self._lock:
            self._state["models"][model] = True
        self._update(percent=end, message=f"{model} is ready.")

    def _pull(self, model: str, start: int, end: int) -> None:
        response = requests.post(
            f"{self.url}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=(10, 3600),
        )
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            payload = json.loads(line)
            completed = payload.get("completed")
            total = payload.get("total")
            fraction = completed / total if total else 0
            percent = start + round((end - start) * min(1, max(0, fraction)))
            self._update(
                phase="downloading",
                percent=percent,
                message=f"Downloading {model} ({percent}%).",
            )
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))

    def chat_stream(self, model: str, messages: list[dict[str, str]]) -> Iterator[dict[str, Any]]:
        response = requests.post(
            f"{self.url}/api/chat",
            json={"model": model, "messages": messages, "stream": True},
            stream=True,
            timeout=(10, 1800),
        )
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if line:
                yield json.loads(line)