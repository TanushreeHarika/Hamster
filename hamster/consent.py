"""Consent broker for interactive approval requests.

Provides a small in-process consent broker that records pending approval
requests and allows programmatic approval/denial. This is a stand-in for the
Async Consent Broker described in the architecture notes.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass
class ConsentRequest:
    request_id: str
    session_id: str
    command: str
    status: str  # pending|approved|denied
    notes: str | None = None


class ConsentBroker:
    def __init__(self) -> None:
        self._requests: dict[str, ConsentRequest] = {}

    def create_request(self, session_id: str, command: str) -> str:
        rid = secrets.token_hex(8)
        req = ConsentRequest(
            request_id=rid, session_id=session_id, command=command, status="pending"
        )
        self._requests[rid] = req
        return rid

    def get_request(self, request_id: str) -> ConsentRequest | None:
        return self._requests.get(request_id)

    def find_request(self, session_id: str, command: str) -> ConsentRequest | None:
        for r in self._requests.values():
            if r.session_id == session_id and r.command == command:
                return r
        return None

    def list_requests(self) -> list[ConsentRequest]:
        return list(self._requests.values())

    def approve(self, request_id: str, notes: str | None = None) -> bool:
        r = self.get_request(request_id)
        if not r:
            return False
        r.status = "approved"
        r.notes = notes
        return True

    def deny(self, request_id: str, notes: str | None = None) -> bool:
        r = self.get_request(request_id)
        if not r:
            return False
        r.status = "denied"
        r.notes = notes
        return True
