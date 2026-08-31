"""hamster.auth.store — Secure OAuth token persistence.

Storage strategy (in priority order):
1. **OS native keychain** via ``keyring`` (optional dependency).
   Install with: ``uv pip install -e ".[auth]"``
   Stores the full JSON payload under ``service="hamster-cli" username="session"``.

2. **Encrypted-restricted JSON file** at ``~/.hamster/auth_session.json``
   created with ``0o600`` permissions (owner read/write only).
   Used automatically when ``keyring`` is not installed or raises an error.

Usage::

    store = SecureTokenStore()
    store.save({"email": "alice@example.com", "access_token": "..."})
    profile = store.load()
    store.delete()
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

_SERVICE_NAME = "hamster-cli"
_KEYRING_USER = "session"
_FALLBACK_PATH = Path.home() / ".hamster" / "auth_session.json"


class SecureTokenStore:
    """Persist OAuth tokens in the OS native keychain with a secure file fallback.

    Args:
        service:       Keyring service name (default: ``"hamster-cli"``).
        fallback_path: JSON file path used when keyring is unavailable.
    """

    def __init__(
        self,
        service: str = _SERVICE_NAME,
        fallback_path: Path = _FALLBACK_PATH,
    ) -> None:
        self._service = service
        self._username = _KEYRING_USER
        self._fallback_path = fallback_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, payload: dict[str, Any]) -> None:
        """Persist *payload* (tokens + profile) to the most secure available backend.

        Tries the OS keyring first; falls back to a ``0o600`` JSON file.
        """
        serialized = json.dumps(payload, indent=2)
        if self._keyring_save(serialized):
            return
        self._file_save(serialized)

    def load(self) -> dict[str, Any] | None:
        """Return the stored session payload, or ``None`` if nothing is stored."""
        raw = self._keyring_load()
        if raw is not None:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

        raw = self._file_load()
        if raw is not None:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None

        return None

    def delete(self) -> None:
        """Remove credentials from all backends (keyring + file)."""
        self._keyring_delete()
        self._file_delete()

    # ------------------------------------------------------------------
    # Keyring backend
    # ------------------------------------------------------------------

    def _keyring_save(self, serialized: str) -> bool:
        """Attempt to save *serialized* to the OS keyring.

        Returns ``True`` on success, ``False`` if keyring is unavailable or
        raises any exception.
        """
        try:
            import keyring  # optional dependency

            keyring.set_password(self._service, self._username, serialized)
            return True
        except (ImportError, RuntimeError, OSError, ValueError):
            return False

    def _keyring_load(self) -> str | None:
        """Return the raw JSON string from the OS keyring, or ``None``."""
        try:
            import keyring

            return keyring.get_password(self._service, self._username)
        except (ImportError, RuntimeError, OSError, ValueError):
            return None

    def _keyring_delete(self) -> None:
        """Remove the entry from the OS keyring (silently ignores all errors)."""
        try:
            import keyring

            keyring.delete_password(self._service, self._username)
        except (ImportError, RuntimeError, OSError, ValueError):
            pass

    # ------------------------------------------------------------------
    # File-based fallback backend
    # ------------------------------------------------------------------

    def _file_save(self, serialized: str) -> None:
        """Write *serialized* to the fallback JSON file at ``0o600`` permissions."""
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename for atomicity
        tmp = self._fallback_path.with_suffix(".tmp")
        tmp.write_text(serialized, encoding="utf-8")
        # Restrict permissions *before* moving into place
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        tmp.replace(self._fallback_path)

    def _file_load(self) -> str | None:
        """Return the raw JSON string from the fallback file, or ``None``."""
        if not self._fallback_path.exists():
            return None
        try:
            return self._fallback_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _file_delete(self) -> None:
        """Remove the fallback JSON file (silently ignores errors)."""
        try:
            self._fallback_path.unlink(missing_ok=True)
        except OSError:
            pass
