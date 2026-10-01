from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request, send_from_directory

from .config import WEB_ROOT
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
                "ram_gb": installed_memory_gb(),
                "p3_warning": p3_warning(),
                "site_url": f"{site_url}/chat",
                "bootstrap": ollama.snapshot(),
            }
        )

    @app.post("/api/account-consent")
    def record_account_consent() -> Any:
        if request.headers.get("Origin") != request.host_url.rstrip("/"):
            return jsonify({"error": "Account consent must be confirmed by this Windows app."}), 403
        consent.accept()
        return jsonify({"consent_accepted": consent.accepted()})

    @app.post("/api/bootstrap/start")
    def start_bootstrap() -> Any:
        if not consent.accepted():
            return jsonify({"error": "Account consent is required before local model setup."}), 423
        ollama.start()
        return jsonify(ollama.snapshot())

    @app.get("/api/bootstrap/status")
    def bootstrap_status() -> Any:
        return jsonify(ollama.snapshot())

    return app