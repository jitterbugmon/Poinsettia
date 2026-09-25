from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import secrets
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

from .config import EULA_VERSION, LEGAL_ROOT, local_data_root


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi_transform(data: bytes, decrypt: bool) -> bytes | None:
    """Protect an install key with the current Windows user's DPAPI key."""
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        source = ctypes.create_string_buffer(data)
        source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
        output_blob = _DataBlob()
        function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
        ok = function(
            ctypes.byref(source_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        if not ok:
            return None
        result = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        kernel32.LocalFree(output_blob.pbData)
        return result
    except (AttributeError, OSError):
        return None


class ConsentStore:
    """Versioned, tamper-evident local consent storage for the Windows build."""

    def __init__(self) -> None:
        self.root = local_data_root()
        self.key_path = self.root / "install.key"
        self.state_path = self.root / "consent.json"

    def _key(self) -> bytes:
        if self.key_path.exists():
            stored = self.key_path.read_bytes()
            unprotected = _dpapi_transform(stored, decrypt=True)
            if unprotected:
                return unprotected
            return stored
        key = secrets.token_bytes(32)
        protected = _dpapi_transform(key, decrypt=False) or key
        self.key_path.write_bytes(protected)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    @staticmethod
    def _document_digest() -> str:
        return hashlib.sha256((LEGAL_ROOT / "eula.md").read_bytes()).hexdigest()

    def _signature(self, version: str, digest: str) -> str:
        payload = f"{version}:{digest}".encode("utf-8")
        return hmac.new(self._key(), payload, hashlib.sha256).hexdigest()

    def accepted(self) -> bool:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            digest = self._document_digest()
            return (
                state.get("version") == EULA_VERSION
                and state.get("document_sha256") == digest
                and hmac.compare_digest(
                    state.get("signature", ""),
                    self._signature(EULA_VERSION, digest),
                )
            )
        except (OSError, ValueError, TypeError):
            return False

    def accept(self) -> None:
        digest = self._document_digest()
        state = {
            "version": EULA_VERSION,
            "document_sha256": digest,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
            "signature": self._signature(EULA_VERSION, digest),
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)