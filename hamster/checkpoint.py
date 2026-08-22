"""Content-Addressable Storage (CAS) checkpoint engine for Hamster.

Each user turn is snapshotted before the agent runs so that ``/undo [N]``
can restore the sandbox workspace to the exact state at any previous turn.

Design
------
Blobs
    Every file's raw bytes are SHA-256 hashed.  The blob is written once to
    ``~/.hamster/checkpoints/blobs/<first2>/<sha256>``.  Identical content
    across turns (or across sessions) shares the same blob — no duplicate
    storage.

Manifests
    A checkpoint is a lightweight JSON file at
    ``~/.hamster/checkpoints/manifests/<checkpoint_id>.json`` that maps
    workspace-relative file paths to their blob SHA-256.  Creating a
    checkpoint only writes blobs for files whose content has changed.

Restore
    Restoring a checkpoint walks the manifest and:
    - Writes (or overwrites) files whose hash differs from the workspace copy.
    - Removes workspace files that are absent from the manifest.
    - Leaves untouched files whose hash matches the manifest.

Public API
----------
::

    store = CheckpointStore()               # or CheckpointStore(base=Path("custom"))

    ckpt_id = store.create_checkpoint(workspace_path, session_id, turn_index)
    result  = store.restore_checkpoint(ckpt_id, workspace_path)
    # result = {"restored": 3, "removed": 1, "unchanged": 7}

    checkpoints = store.list_checkpoints(session_id)   # list[dict], turn-ordered
    store.delete_checkpoint(ckpt_id)
    store.gc_blobs()   # delete unreferenced blobs
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

# Default base directory — siblings of the session DB so everything is in one place
DEFAULT_BASE: Path = Path.home() / ".hamster" / "checkpoints"

# Directories to skip when snapshotting the workspace
_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv",
    "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "node_modules", "dist", "build",
})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CheckpointStore:
    """CAS-backed workspace checkpoint store.

    Args:
        base: Root directory for blob and manifest storage.
              Defaults to ``~/.hamster/checkpoints/``.
    """

    def __init__(self, base: Path | None = None) -> None:
        self._base = Path(base) if base is not None else DEFAULT_BASE
        self._blobs = self._base / "blobs"
        self._manifests = self._base / "manifests"
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._manifests.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Blob store
    # ------------------------------------------------------------------

    def _blob_path(self, sha: str) -> Path:
        """Return the filesystem path for a blob SHA."""
        return self._blobs / sha[:2] / sha

    def _store_blob(self, data: bytes) -> str:
        """Write *data* to the blob store and return its SHA-256.

        Idempotent — if the blob already exists it is not overwritten.
        """
        sha = _sha256(data)
        dest = self._blob_path(sha)
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        return sha

    def _read_blob(self, sha: str) -> bytes:
        """Return the raw bytes for a blob SHA.

        Raises:
            FileNotFoundError: If the blob is not found in the store.
        """
        path = self._blob_path(sha)
        if not path.exists():
            raise FileNotFoundError(f"Blob not found: {sha!r}")
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Manifest helpers
    # ------------------------------------------------------------------

    def _manifest_path(self, checkpoint_id: str) -> Path:
        return self._manifests / f"{checkpoint_id}.json"

    def _write_manifest(self, checkpoint_id: str, payload: dict[str, Any]) -> None:
        self._manifest_path(checkpoint_id).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _read_manifest(self, checkpoint_id: str) -> dict[str, Any]:
        path = self._manifest_path(checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Public API — checkpoints
    # ------------------------------------------------------------------

    def create_checkpoint(
        self,
        workspace_path: str | Path,
        session_id: str = "",
        turn_index: int = 0,
    ) -> str:
        """Snapshot the current workspace state and return a checkpoint ID.

        Only files that differ between calls contribute new blobs; unchanged
        content reuses the existing blob (deduplication).

        Args:
            workspace_path: Root of the mutable sandbox workspace directory.
            session_id:     The active session identifier (stored in manifest).
            turn_index:     Which user turn this checkpoint represents.

        Returns:
            A short ``ckpt_<hex>`` identifier string.
        """
        workspace = Path(workspace_path)
        checkpoint_id = f"ckpt_{uuid.uuid4().hex[:10]}"

        files: dict[str, str] = {}  # rel_path → sha256

        if workspace.exists():
            for file_path in sorted(workspace.rglob("*")):
                if not file_path.is_file():
                    continue
                # Skip ignored top-level directories
                rel = file_path.relative_to(workspace)
                if rel.parts and rel.parts[0] in _IGNORE_DIRS:
                    continue
                data = file_path.read_bytes()
                sha = self._store_blob(data)
                files[str(rel)] = sha

        manifest: dict[str, Any] = {
            "checkpoint_id": checkpoint_id,
            "session_id": session_id,
            "turn_index": turn_index,
            "files": files,
        }
        self._write_manifest(checkpoint_id, manifest)
        return checkpoint_id

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        workspace_path: str | Path,
    ) -> dict[str, int]:
        """Restore the workspace to the state captured by *checkpoint_id*.

        - Files in the manifest whose content differs from the workspace are overwritten.
        - Workspace files absent from the manifest are deleted.
        - Workspace files whose hash matches the manifest are left untouched.

        Args:
            checkpoint_id:  The checkpoint to restore.
            workspace_path: Root of the mutable sandbox workspace directory.

        Returns:
            ``{"restored": N, "removed": N, "unchanged": N}``

        Raises:
            FileNotFoundError: If the checkpoint_id is unknown.
        """
        manifest = self._read_manifest(checkpoint_id)
        workspace = Path(workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)

        target_files: dict[str, str] = manifest.get("files", {})
        restored = removed = unchanged = 0

        # --- Restore / update files in the manifest ---
        for rel_str, sha in target_files.items():
            dest = workspace / rel_str
            if dest.exists():
                current_sha = _sha256(dest.read_bytes())
                if current_sha == sha:
                    unchanged += 1
                    continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self._read_blob(sha))
            restored += 1

        # --- Remove workspace files absent from the manifest ---
        target_set = set(target_files.keys())
        if workspace.exists():
            for file_path in sorted(workspace.rglob("*")):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(workspace)
                if rel.parts and rel.parts[0] in _IGNORE_DIRS:
                    continue
                if str(rel) not in target_set:
                    file_path.unlink(missing_ok=True)
                    # Clean up empty parent directories
                    parent = file_path.parent
                    while parent != workspace:
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
                    removed += 1

        return {"restored": restored, "removed": removed, "unchanged": unchanged}

    def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """Return all checkpoints for *session_id*, ordered by ``turn_index`` ascending.

        Args:
            session_id: Session to filter by.

        Returns:
            List of manifest dicts (without the ``files`` blob map to keep it lightweight).
        """
        results: list[dict[str, Any]] = []
        for path in sorted(self._manifests.glob("ckpt_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("session_id") == session_id:
                results.append({
                    "checkpoint_id": data["checkpoint_id"],
                    "session_id": data["session_id"],
                    "turn_index": data.get("turn_index", 0),
                    "file_count": len(data.get("files", {})),
                })
        results.sort(key=lambda d: d["turn_index"])
        return results

    def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Remove the manifest for *checkpoint_id*.

        Blobs are shared and not deleted here; call :meth:`gc_blobs` to
        reclaim unreferenced blobs.
        """
        path = self._manifest_path(checkpoint_id)
        path.unlink(missing_ok=True)

    def gc_blobs(self) -> int:
        """Delete blobs that are not referenced by any manifest.

        Returns:
            Number of blobs deleted.
        """
        # Collect all referenced SHAs
        referenced: set[str] = set()
        for path in self._manifests.glob("ckpt_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                referenced.update(data.get("files", {}).values())
            except (json.JSONDecodeError, OSError):
                continue

        deleted = 0
        for blob_path in self._blobs.rglob("*"):
            if not blob_path.is_file():
                continue
            if blob_path.name not in referenced:
                blob_path.unlink(missing_ok=True)
                deleted += 1
        return deleted

    def __repr__(self) -> str:
        return f"CheckpointStore(base={self._base!r})"
