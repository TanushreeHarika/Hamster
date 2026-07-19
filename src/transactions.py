from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
import os


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    original_text: str | None
    exists: bool


class TransactionManager:
    """Snapshot files before mutation and restore them on rollback.

    The manager is intentionally lightweight and can be used as an optional
    utility by the main agent loop without changing the existing call flow.
    """

    def __init__(self, targets: Iterable[str]) -> None:
        self._targets = tuple(targets)
        self._snapshots: dict[str, FileSnapshot] = self._snapshot_all(self._targets)

    @staticmethod
    def _snapshot_all(targets: Iterable[str]) -> dict[str, FileSnapshot]:
        snapshots: dict[str, FileSnapshot] = {}
        for target in targets:
            resolved = os.path.realpath(target)
            path = Path(resolved)
            exists = path.exists()
            snapshots[resolved] = FileSnapshot(
                path=resolved,
                original_text=path.read_text(encoding="utf-8") if exists and path.is_file() else None,
                exists=exists,
            )
        return snapshots

    def rollback(self) -> dict[str, str]:
        restored: dict[str, str] = {}
        for resolved_path, snapshot in self._snapshots.items():
            path = Path(resolved_path)
            if snapshot.exists and snapshot.original_text is not None:
                path.write_text(snapshot.original_text, encoding="utf-8")
                restored[resolved_path] = "restored"
            elif path.exists():
                path.unlink(missing_ok=True)
                restored[resolved_path] = "removed"
        return restored

    def run(self, operation: Callable[[], Any], *, verifier: Callable[[], bool] | None = None) -> Any:
        """Execute an operation and automatically rollback on failure or verifier failure."""

        try:
            result = operation()
            if verifier is not None and not verifier():
                raise AssertionError("Transaction verification failed.")
            return result
        except Exception:
            self.rollback()
            raise


def snapshot_files(targets: Iterable[str]) -> dict[str, FileSnapshot]:
    return TransactionManager._snapshot_all(targets)


def rollback_snapshot(snapshot: dict[str, FileSnapshot]) -> dict[str, str]:
    manager = TransactionManager([])
    manager._snapshots = snapshot
    return manager.rollback()
