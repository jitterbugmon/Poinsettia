"""Bounded, metadata-only diagnostics for the frozen Windows retrieval path."""

from __future__ import annotations

import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import re
import sys

from .config import local_data_root


LOGGER_NAME = "poinsettia.retrieval"
EVENTS = {
    "runtime_start", "search_start", "search_http", "search_parsed",
    "search_evidence", "search_error", "search_complete", "page_http",
    "page_error", "page_rejected", "context_ready",
}
STRING_VALUES = {
    "endpoint": {"HTML POST", "HTML GET", "Lite GET"},
    "reason": {"tls", "proxy", "timeout", "connection", "parse", "unexpected", "challenge"},
    "runtime_format": {"source", "bytecode"},
    "error_type": {
        "SSLError", "ProxyError", "Timeout", "ConnectTimeout", "ReadTimeout",
        "ConnectionError", "HTTPError", "InvalidURL", "MissingSchema",
        "InvalidSchema", "TooManyRedirects", "ValueError", "TypeError",
        "OSError", "JSONDecodeError", "FeatureNotFound", "ParserRejectedMarkup",
        "RuntimeError", "AttributeError", "KeyError", "UnicodeDecodeError",
    },
}
NUMBER_FIELDS = {
    "status", "duration_ms", "links", "candidates", "pages", "snippets",
    "sources", "context_chars",
}
BOOL_FIELDS = {"frozen", "challenge", "retried"}


class RetrievalRecordFilter(logging.Filter):
    def filter(self, record):
        return (
            getattr(record, "retrieval_event", None) in EVENTS
            and isinstance(getattr(record, "retrieval_fields", None), dict)
        )


class MetadataFormatter(logging.Formatter):
    def format(self, record):
        # Never render message, args, exception text, URLs, query or page text.
        safe = {}
        for key, value in record.retrieval_fields.items():
            if key in STRING_VALUES and isinstance(value, str):
                if value in STRING_VALUES[key]:
                    safe[key] = value
                elif key == "error_type":
                    safe[key] = "OtherError"
            elif key in NUMBER_FIELDS and type(value) in (int, float):
                if 0 <= value <= 1e12 and math.isfinite(value):
                    safe[key] = value
            elif key in BOOL_FIELDS and type(value) is bool:
                safe[key] = value
            elif key == "runtime_sha256" and isinstance(value, str):
                if re.fullmatch(r"[0-9a-f]{64}", value):
                    safe[key] = value
        return (
            f"{self.formatTime(record)} {record.retrieval_event} "
            + json.dumps(safe, sort_keys=True)
        )


def configure_diagnostics(log_directory: Path | None = None) -> Path:
    directory = log_directory if log_directory is not None else local_data_root() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "retrieval.log"
    logger = logging.getLogger(LOGGER_NAME)
    # Idempotent startup; do not duplicate handlers on reinitialization.
    for handler in list(logger.handlers):
        if getattr(handler, "_poinsettia_retrieval", False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8"
    )
    handler._poinsettia_retrieval = True
    handler.addFilter(RetrievalRecordFilter())
    handler.setFormatter(MetadataFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return path


def record_runtime(site_directory: Path) -> None:
    runtime = site_directory / "main.pyc"
    if not runtime.is_file():
        runtime = site_directory / "main.py"
    logging.getLogger(LOGGER_NAME).info(
        "runtime_start",
        extra={
            "retrieval_event": "runtime_start",
            "retrieval_fields": {
                "frozen": bool(getattr(sys, "frozen", False)),
                "runtime_format": "bytecode" if runtime.suffix == ".pyc" else "source",
                "runtime_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
            },
        },
    )