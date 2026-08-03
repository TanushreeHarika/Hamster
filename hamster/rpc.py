"""Minimal RPC Gateway and Session Manager skeleton for Hamster.

This provides a lightweight in-process API surface so higher-level code
and tests can call the sandbox control plane without a network layer.

The implementations are intentionally small and blocking; they should be
replaced with an actual gRPC/IPC server in a later iteration.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from src.transactions import rollback_snapshot, snapshot_files, FileSnapshot as TxFileSnapshot

import hamster.tools as tools
from hamster.policy import CommandASTAnalyzer, SecurityPolicyEngine
from hamster.consent import ConsentBroker


@dataclass
class Session:
    session_id: str
    subject: str = "agent"
    approved_scopes: set[str] = None

    def __post_init__(self) -> None:
        if self.approved_scopes is None:
            self.approved_scopes = set()


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def create_session(self, subject: str = "agent") -> str:
        sid = secrets.token_hex(8)
        self._sessions[sid] = Session(session_id=sid, subject=subject)
        return sid

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def approve_scope(self, session_id: str, scope: str) -> bool:
        s = self.get_session(session_id)
        if not s:
            return False
        s.approved_scopes.add(scope)
        return True


class RPCGateway:
    def __init__(self, session_manager: SessionManager) -> None:
        self.sessions = session_manager
        self.policy = SecurityPolicyEngine()
        self.consent = ConsentBroker()

    # ---- Session helpers
    def open_session(self, subject: str = "agent") -> str:
        return self.sessions.create_session(subject)

    # ---- Command execution
    def execute_command(self, session_id: str, command: str) -> Dict[str, Any]:
        session = self.sessions.get_session(session_id)
        if session is None:
            return {"error": "invalid session"}

        analysis = CommandASTAnalyzer.analyze(command)
        if analysis.get("violations"):
            return {"policy_decision": "DENIED", "violations": analysis.get("violations")}

        # If suspicious, check if the primary binary is pre-approved for this subject
        if analysis.get("suspects"):
            primary = analysis.get("primary", "")
            if primary and self.policy.is_binary_allowed(session.subject, primary):
                # proceed as allowed for this subject
                pass
            else:
                # if there's an existing consent request and it's approved, allow
                existing = self.consent.find_request(session.session_id, command)
                if existing and existing.status == "approved":
                    pass
                else:
                    # create a consent request for human approval
                    cid = self.consent.create_request(session.session_id, command)
                    return {"policy_decision": "CONSENT_PENDING", "consent_id": cid, "suspects": analysis.get("suspects"), "notes": analysis.get("notes", [])}

        # Basic policy check placeholder — real policy checks go here
        pd = self.policy.check(session.subject, "exec")
        if not pd.allowed:
            return {"policy_decision": "DENIED", "reason": pd.reason}

        # Delegate to existing tools implementation (which prompts for approval)
        out = tools.run_sandbox_command(command)
        return {"policy_decision": "ALLOWED_AUTO", "output": out}

    def spawn_pty(self, session_id: str, pty_spec: Dict[str, Any]) -> Dict[str, Any]:
        # PTY streaming interfaces are out of scope for this skeleton.
        return {"error": "spawn_pty not implemented in RPC skeleton"}

    # ---- File operations
    def read_file(self, session_id: str, filepath: str) -> Dict[str, Any]:
        session = self.sessions.get_session(session_id)
        if session is None:
            return {"error": "invalid session"}
        # require explicit read approval for codebase reads
        if "codebase" not in session.approved_scopes:
            return {"error": "read scope not approved", "required_scope": "codebase"}
        data = tools.read_file(filepath)
        return {"data": data}

    def write_file(self, session_id: str, filepath: str, content: str) -> Dict[str, Any]:
        session = self.sessions.get_session(session_id)
        if session is None:
            return {"error": "invalid session"}
        res = tools.write_file(filepath, content)
        return {"result": res}

    # ---- Snapshot / restore
    def create_checkpoint(self, session_id: str, targets: Iterable[str]) -> Dict[str, Any]:
        # Use src.transactions.snapshot_files to capture current state
        snap = snapshot_files(targets)
        # Return a serializable snapshot (caller can persist externally)
        serializable = {
            k: {"path": v.path, "original_text": v.original_text, "exists": v.exists}
            for k, v in snap.items()
        }
        return {"snapshot": serializable}

    def restore_checkpoint(self, session_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        # Reconstruct FileSnapshot objects and rollback
        reconstructed: dict[str, TxFileSnapshot] = {}
        for k, v in snapshot.items():
            reconstructed[k] = TxFileSnapshot(path=v["path"], original_text=v["original_text"], exists=v["exists"])  # type: ignore[arg-type]
        res = rollback_snapshot(reconstructed)
        return {"restored": res}

    def get_diff(self, session_id: str, path_a: str | None = None, path_b: str | None = None) -> Dict[str, Any]:
        # Minimal listing-based diff: return sandbox file listing for now
        listing = tools.list_sandbox_files()
        return {"files": listing}
