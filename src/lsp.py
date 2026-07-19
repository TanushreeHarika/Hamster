from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Diagnostic:
    path: str
    line: int
    column: int
    message: str
    severity: str = "warning"


class LSPBridge:
    """Utility hook for optional local language-server inspection.

    This module intentionally stays lightweight and does not add any new runtime
    dependency beyond the local shell environment.
    """

    def __init__(self, server_name: str = "pyright") -> None:
        self.server_name = server_name
        self.server_path = shutil.which(server_name)

    def available(self) -> bool:
        return self.server_path is not None

    def diagnostics(self, filepath: str) -> list[Diagnostic]:
        if not self.available():
            return []

        target = Path(filepath).resolve()
        command = [self.server_path, "--outputjson", str(target)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError:
            return []

        output = completed.stdout.strip()
        if not output:
            return []

        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return self._fallback_parse_diagnostics(output)

        diagnostics: list[Diagnostic] = []
        for entry in payload.get("generalDiagnostics", []):
            diagnostics.append(
                Diagnostic(
                    path=str(entry.get("file", filepath)),
                    line=int(entry.get("range", {}).get("start", {}).get("line", 0)) + 1,
                    column=int(entry.get("range", {}).get("start", {}).get("character", 0)) + 1,
                    message=str(entry.get("message", "")),
                    severity=str(entry.get("severity", "warning")).lower(),
                )
            )
        return diagnostics

    def definition_lookup(self, filepath: str, symbol: str) -> dict[str, Any]:
        if not self.available():
            return {
                "status": "unavailable",
                "server": self.server_name,
                "symbol": symbol,
                "message": "No local language server detected on PATH.",
            }

        target = Path(filepath).resolve()
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        matches: list[dict[str, int]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if f"def {symbol}" in line or f"class {symbol}" in line:
                matches.append({"line": line_number, "column": line.find(symbol) + 1})

        if matches:
            return {
                "status": "resolved",
                "server": self.server_name,
                "symbol": symbol,
                "matches": matches,
            }

        return {
            "status": "unresolved",
            "server": self.server_name,
            "symbol": symbol,
            "message": f"No local definition match found for {symbol!r} in {filepath}.",
        }

    @staticmethod
    def _fallback_parse_diagnostics(text: str) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for line in text.splitlines():
            if ":" not in line:
                continue
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            path = parts[0].strip()
            line_no = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
            remainder = parts[2].strip()
            severity = "warning"
            if "error" in remainder.lower():
                severity = "error"
            diagnostics.append(Diagnostic(path=path, line=max(1, line_no), column=1, message=remainder, severity=severity))
        return diagnostics


def parse_local_diagnostics(filepath: str) -> list[Diagnostic]:
    return LSPBridge().diagnostics(filepath)


def resolve_symbol_definition(filepath: str, symbol: str) -> dict[str, Any]:
    return LSPBridge().definition_lookup(filepath, symbol)
