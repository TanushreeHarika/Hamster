"""Virtual filesystem manager skeleton for Hamster.

Provides a `VFSManager` that wraps the existing `TempSandbox` layout and offers
basic snapshot and listing helpers used by the CLI and higher-level code.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from src.sandbox import TempSandbox


@dataclass
class VFSSnapshot:
    files: dict[str, str]


class VFSManager:
    def __init__(self, sandbox: TempSandbox) -> None:
        self.sandbox = sandbox

    def list_files(self, pattern: str = "") -> list[str]:
        root = self.sandbox.root
        out: list[str] = []
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(root))
                if not pattern or pattern in rel:
                    out.append(rel)
        return out

    def snapshot_paths(self, paths: Iterable[str]) -> VFSSnapshot:
        files: dict[str, str] = {}
        for p in paths:
            abs_p = Path(p)
            if abs_p.exists() and abs_p.is_file():
                files[str(abs_p)] = abs_p.read_text(encoding="utf-8")
            else:
                files[str(abs_p)] = ""  # missing -> empty marker
        return VFSSnapshot(files=files)
