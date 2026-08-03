"""Security & policy subsystem skeleton for Hamster.

Contains a minimal `SecurityPolicyEngine` and `CommandASTAnalyzer` to be
implemented further. These are intentionally lightweight stubs so the rest of
the codebase can import and evolve them incrementally.
"""
from __future__ import annotations

import re
import math
import shlex
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str | None = None


class SecurityPolicyEngine:
    """Maintain granular permission matrices and make policy decisions.

    This is a small, testable surface that can be expanded into a full rule
    engine backed by YAML/JSON policies or a database.
    """

    def __init__(self) -> None:
        self._capabilities: Dict[str, set[str]] = {}
        self._binary_whitelist: Dict[str, set[str]] = {}

    def allow(self, subject: str, capability: str) -> None:
        self._capabilities.setdefault(subject, set()).add(capability)

    def deny(self, subject: str, capability: str) -> None:
        self._capabilities.setdefault(subject, set()).discard(capability)

    def check(self, subject: str, capability: str) -> PolicyDecision:
        allowed = capability in self._capabilities.get(subject, set())
        return PolicyDecision(allowed=allowed, reason=None if allowed else "denied by default")

    def allow_binary(self, subject: str, binary: str) -> None:
        self._binary_whitelist.setdefault(subject, set()).add(binary)

    def deny_binary(self, subject: str, binary: str) -> None:
        self._binary_whitelist.setdefault(subject, set()).discard(binary)

    def is_binary_allowed(self, subject: str, binary: str) -> bool:
        return binary in self._binary_whitelist.get(subject, set())


class CommandASTAnalyzer:
    """Very small command analyzer that applies heuristics to detect unsafe commands.

    This is NOT a full parser; it's a starting point that can be replaced with a
    proper AST-based shell parser in future iterations.
    """

    # Patterns considered immediate violations
    VIOLATION_PATTERNS: List[re.Pattern] = [
        re.compile(r"(^|[;&|]\s*)sudo(\s|$)", re.IGNORECASE),
        re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
        re.compile(r"\b(chmod|chown|su|setuid)\b", re.IGNORECASE),
        re.compile(r"\bdd\b[^;&|]*\bif=/", re.IGNORECASE),
        re.compile(r"\b(mkfs|wipefs)\b", re.IGNORECASE),
    ]

    # Patterns that are suspicious and may need consent
    SUSPICIOUS_PATTERNS: List[re.Pattern] = [
        re.compile(r"\$\(|`"),  # subshells
        re.compile(r"(curl|wget|fetch)[^|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
        re.compile(r"base64\s+-d[^;&|]*\|\s*(sh|bash|zsh|python|python3)\b", re.IGNORECASE),
        re.compile(r"/dev/(sd|mmcblk|nvme|zero|tty)"),
        re.compile(r"/dev/tcp"),
    ]

    # Heuristic for high-entropy tokens (possible secrets or encoded payloads)
    LONG_BASE64_RE = re.compile(r"[A-Za-z0-9+/=]{40,}")

    @staticmethod
    def _shannon_entropy(s: str) -> float:
        if not s:
            return 0.0
        freq = {}
        for ch in s:
            freq[ch] = freq.get(ch, 0) + 1
        entropy = 0.0
        length = len(s)
        for v in freq.values():
            p = v / length
            entropy -= p * math.log2(p)
        return entropy

    @classmethod
    def analyze(cls, command: str) -> Dict[str, Any]:
        raw = command or ""
        findings: Dict[str, Any] = {"raw": raw, "violations": [], "suspects": [], "notes": []}

        if not raw.strip():
            findings["violations"].append("empty_command")
            return {**findings, "safe": False}

        # Immediate violations
        for pat in cls.VIOLATION_PATTERNS:
            if pat.search(raw):
                findings["violations"].append(pat.pattern)

        # Suspicious patterns
        for pat in cls.SUSPICIOUS_PATTERNS:
            if pat.search(raw):
                findings["suspects"].append(pat.pattern)

        # Detect long base64-like tokens and evaluate entropy
        for m in cls.LONG_BASE64_RE.finditer(raw):
            token = m.group(0)
            ent = cls._shannon_entropy(token)
            if ent > 4.0:
                findings["suspects"].append("high_entropy_token")
                findings["notes"].append(f"token_entropy={ent:.2f}")

        safe = not findings["violations"] and not findings["suspects"]
        # extract primary binary
        try:
            parts = shlex.split(raw)
            primary = parts[0] if parts else ""
        except Exception:
            primary = ""
        return {**findings, "safe": bool(safe), "primary": primary}
