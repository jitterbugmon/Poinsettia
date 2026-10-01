from __future__ import annotations

import os
import sys
import json
from pathlib import Path


RELEASE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
WEB_ROOT = RELEASE_ROOT / "dist" if (RELEASE_ROOT / "dist").exists() else RELEASE_ROOT / "web"
LEGAL_ROOT = RELEASE_ROOT / "legal"
MODEL_ROOT = RELEASE_ROOT / "models"

EULA_VERSION = "windows-1.1"
PRIVACY_VERSION = "windows-1.1"
OLLAMA_URL = os.environ.get("POINSETTIA_OLLAMA_URL", "http://127.0.0.1:11434")


def _ollama_release_pin() -> dict[str, str]:
    path = RELEASE_ROOT / "ollama_pin.json"
    if not path.is_file():
        return {}
    try:
        values = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return values if isinstance(values, dict) else {}


_OLLAMA_PIN = _ollama_release_pin()
OLLAMA_INSTALLER_URL = (
    os.environ.get("POINSETTIA_OLLAMA_INSTALLER_URL")
    or str(_OLLAMA_PIN.get("url") or "")
    or "https://ollama.com/download/OllamaSetup.exe"
)
OLLAMA_INSTALLER_SHA256 = (
    os.environ.get("POINSETTIA_OLLAMA_SHA256")
    or str(_OLLAMA_PIN.get("sha256") or "")
).strip().lower()

# The copied website calls these local Ollama models "poinsettia" and "p3".
# Keeping those names means its exact, unmodified chat routes work in the
# Windows mirror without rewriting the website source.
P2_MODEL = "poinsettia"
P3_MODEL = "p3"
P2_BASE_MODEL = "gemma4:e4b"
P3_BASE_MODEL = "gemma4:12b"
P4_FAX_MODEL = "p4-fax"
P4_FAX_BASE_MODEL = "gemma4:26b"
P4_CANDOR_MODEL = "p4-candor"
P4_CANDOR_BASE_MODEL = "gemma4:31b"
P4_RELEASE_DATE = None

SYSTEM_PROMPTS = {
    P2_MODEL: (
        "You are Poinsettia 2, a helpful and knowledgeable local assistant. "
        "Answer accurately, clearly, and concisely. Do not make jokes about "
        "poinsettias. Respond in the user's language."
    ),
    P3_MODEL: (
        "You are Poinsettia 3.9, an advanced multimodal local assistant. Be accurate, "
        "clear, and concise. The desktop application may provide retrieved "
        "web results in the prompt; treat those results as the source for "
        "current facts and do not claim to have searched independently. "
        "Respond in the user's language."
    ),
    P4_FAX_MODEL: (
        "You are Poinsettia 4.0 Fax, a friendly, creative, expressive, and "
        "helpful multimodal local assistant. Retrieved web results may be included "
        "in the prompt; use "
        "them as the source for current facts. Image input is supported, but "
        "audio and speech input are not supported. Respond in the user's language."
    ),
    P4_CANDOR_MODEL: (
        "You are Poinsettia 4.0 Candor, a direct, candid, and straight-to-the-point "
        "multimodal local assistant. Retrieved web results may be included in the "
        "prompt; use "
        "them as the source for current facts. Image input is supported, but "
        "audio and speech input are not supported. Respond in the user's language."
    ),
}


def local_data_root() -> Path:
    """Return a per-user data location without touching the repository."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else RELEASE_ROOT / "user_data"
    path = root / "Poinsettia" / "Windows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def p4_is_released(today=None) -> bool:
    """Poinsettia 4.0 is available immediately in the current release."""
    return True