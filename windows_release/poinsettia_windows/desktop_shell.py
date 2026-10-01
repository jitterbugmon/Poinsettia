from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from .config import EULA_VERSION, LEGAL_ROOT, PRIVACY_VERSION, WEB_ROOT
from .hardware import installed_memory_gb, p3_warning
from .ollama import OllamaManager
from .security import ConsentStore


def create_shell_app(site_url: str, ollama: OllamaManager | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    consent = ConsentStore()
    ollama = ollama or OllamaManager()

    @app.get("/")
    def shell() -> Any:
        return send_from_directory(WEB_ROOT, "desktop_shell.html")

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
                "site_url": f"{site_url}/chat",
                "bootstrap": ollama.snapshot(),
            }
        )

    @app.get("/api/legal/<document>")
    def legal(document: str) -> Any:
        files = {"eula": "eula.md", "privacy": "privacy.md"}
        filename = files.get(document)
        if not filename:
            return jsonify({"error": "Document not found."}), 404
        return send_from_directory(LEGAL_ROOT, filename, mimetype="text/plain")

    @app.post("/api/consent")
    def accept_consent() -> Any:
        consent.accept()
        if consent.accepted():
            ollama.start()
        return jsonify({"consent_accepted": consent.accepted()})

    @app.post("/api/bootstrap/start")
    def start_bootstrap() -> Any:
        if not consent.accepted():
            return jsonify({"error": "Accept the current EULA first."}), 423
        ollama.start()
        return jsonify(ollama.snapshot())

    @app.get("/api/bootstrap/status")
    def bootstrap_status() -> Any:
        return jsonify(ollama.snapshot())

    return app