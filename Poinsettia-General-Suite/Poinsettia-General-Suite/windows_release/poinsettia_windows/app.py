from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory

from .config import (
    EULA_VERSION,
    LEGAL_ROOT,
    P2_MODEL,
    P3_MODEL,
    P4_CANDOR_MODEL,
    P4_FAX_MODEL,
    PRIVACY_VERSION,
    WEB_ROOT,
)
from .hardware import installed_memory_gb, p3_warning
from .ollama import OllamaManager
from .security import ConsentStore


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    consent = ConsentStore()
    ollama = OllamaManager()

    @app.get("/")
    def home() -> Any:
        return send_from_directory(WEB_ROOT, "index.html")

    @app.get("/assets/<path:filename>")
    def assets(filename: str) -> Any:
        return send_from_directory(WEB_ROOT, filename)

    @app.get("/favicon.ico")
    def favicon() -> Any:
        return send_from_directory(WEB_ROOT, "favicon.svg", mimetype="image/svg+xml")

    @app.get("/api/state")
    def state() -> Any:
        return jsonify(
            {
                "consent_accepted": consent.accepted(),
                "eula_version": EULA_VERSION,
                "privacy_version": PRIVACY_VERSION,
                "ram_gb": installed_memory_gb(),
                "p3_warning": p3_warning(),
                "bootstrap": ollama.snapshot(),
            }
        )

    @app.get("/api/legal/<document>")
    def legal(document: str) -> Any:
        files = {"eula": "eula.md", "privacy": "privacy.md"}
        filename = files.get(document)
        if not filename:
            return jsonify({"error": "Document not found."}), 404
        path = LEGAL_ROOT / filename
        return Response(path.read_text(encoding="utf-8"), mimetype="text/plain")

    @app.post("/api/consent")
    def accept_consent() -> Any:
        consent.accept()
        return jsonify({"consent_accepted": consent.accepted(), "eula_version": EULA_VERSION})

    @app.post("/api/bootstrap/start")
    def start_bootstrap() -> Any:
        if not consent.accepted():
            return jsonify({"error": "Accept the current EULA before starting local models."}), 423
        ollama.start()
        return jsonify(ollama.snapshot())

    @app.get("/api/bootstrap/status")
    def bootstrap_status() -> Any:
        return jsonify(ollama.snapshot())

    @app.post("/api/chat")
    def chat() -> Any:
        if not consent.accepted():
            return jsonify({"error": "Current EULA acceptance is required."}), 423
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode", "p2")
        models = {
            "p2": P2_MODEL,
            "p3": P3_MODEL,
            P4_FAX_MODEL: P4_FAX_MODEL,
            P4_CANDOR_MODEL: P4_CANDOR_MODEL,
        }
        if mode not in models:
            return jsonify({"error": "Unknown model."}), 400
        model = models[mode]
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": "A non-empty messages list is required."}), 400

        def generate() -> Any:
            try:
                for item in ollama.chat_stream(model, messages):
                    yield json.dumps(item, ensure_ascii=False) + "\n"
            except Exception as exc:
                yield json.dumps({"error": str(exc)}) + "\n"

        return Response(generate(), mimetype="application/x-ndjson")

    @app.get("/health")
    def health() -> Any:
        return jsonify({"ok": True, "release": "windows"})

    return app