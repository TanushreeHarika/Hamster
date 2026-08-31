"""Audit logger and secret redactor skeleton for Hamster.

Provides a simple append-only logger and a streaming redactor utility. The
implementation is intentionally small and testable; production-grade logging and
cryptographic append-only ledgers can be integrated later.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class AuditEvent:
    timestamp: str
    session_id: str
    event_type: str
    payload: dict[str, Any]


class SecretRedactor:
    DEFAULT_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"[A-Za-z0-9_\-]{32,}"),
    )

    @classmethod
    def redact(cls, text: str) -> str:
        out = text
        for p in cls.DEFAULT_PATTERNS:
            out = p.sub("[REDACTED_SECRET]", out)
        return out


class AuditLogger:
    def __init__(self, logfile: str | Path = "hamster_audit.log") -> None:
        self.logfile = Path(logfile)
        self.logfile.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self, session_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        event = AuditEvent(
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )
        serialized = json.dumps(event.__dict__, ensure_ascii=False)
        serialized = SecretRedactor.redact(serialized)
        with self.logfile.open("a", encoding="utf-8") as fh:
            fh.write(serialized + "\n")
