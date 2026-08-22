"""Unit tests for the CAS checkpoint engine and session-store checkpoint cross-references.

All tests use temporary directories — no real ~/.hamster/ data is touched.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hamster.checkpoint import CheckpointStore, _sha256
from hamster.session_store import SessionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ckpt(tmp: str) -> CheckpointStore:
    return CheckpointStore(base=Path(tmp) / "checkpoints")


def _make_store(tmp: str) -> SessionStore:
    return SessionStore(path=Path(tmp) / "sessions.db")


def _write(root: Path, rel: str, content: str) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Blob store primitives
# ---------------------------------------------------------------------------

class TestCheckpointBlobs(unittest.TestCase):
    def test_store_and_retrieve_blob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            data = b"hello world"
            sha = store._store_blob(data)
            self.assertEqual(sha, _sha256(data))
            self.assertEqual(store._read_blob(sha), data)

    def test_blob_deduplication(self) -> None:
        """Storing the same content twice returns the same SHA and stores only 1 file."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            data = b"duplicate content"
            sha1 = store._store_blob(data)
            sha2 = store._store_blob(data)
            self.assertEqual(sha1, sha2)
            # Only one blob file exists
            blobs = list((Path(tmp) / "checkpoints" / "blobs").rglob("*"))
            blob_files = [p for p in blobs if p.is_file()]
            self.assertEqual(len(blob_files), 1)

    def test_unknown_blob_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            with self.assertRaises(FileNotFoundError):
                store._read_blob("deadbeef" * 8)


# ---------------------------------------------------------------------------
# 2. Checkpoint creation
# ---------------------------------------------------------------------------

class TestCheckpointCreate(unittest.TestCase):
    def test_create_returns_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "file.py", "x = 1")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)
            self.assertTrue(ckpt_id.startswith("ckpt_"))

    def test_create_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "a.py", "a = 1")
            _write(workspace, "b.py", "b = 2")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=1)
            manifest_path = Path(tmp) / "checkpoints" / "manifests" / f"{ckpt_id}.json"
            self.assertTrue(manifest_path.exists())

    def test_create_all_files_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "x.py", "x")
            _write(workspace, "sub/y.py", "y")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)
            manifest = store._read_manifest(ckpt_id)
            file_keys = set(manifest["files"].keys())
            self.assertIn("x.py", file_keys)
            self.assertIn("sub/y.py", file_keys)

    def test_create_empty_workspace_makes_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)
            manifest = store._read_manifest(ckpt_id)
            self.assertEqual(manifest["files"], {})


# ---------------------------------------------------------------------------
# 3. Checkpoint restore
# ---------------------------------------------------------------------------

class TestCheckpointRestore(unittest.TestCase):
    def test_round_trip_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "main.py", "original content")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            # Modify the file
            _write(workspace, "main.py", "modified content")

            result = store.restore_checkpoint(ckpt_id, workspace)
            self.assertEqual(_read(workspace, "main.py"), "original content")
            self.assertEqual(result["restored"], 1)

    def test_new_file_removed_on_restore(self) -> None:
        """Files added after the checkpoint should be deleted on restore."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "base.py", "base")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            # Add a new file after the checkpoint
            _write(workspace, "extra.py", "extra")
            self.assertTrue((workspace / "extra.py").exists())

            store.restore_checkpoint(ckpt_id, workspace)
            self.assertFalse((workspace / "extra.py").exists())

    def test_deleted_file_restored(self) -> None:
        """Files deleted after the checkpoint should be recreated on restore."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "important.py", "important")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            # Delete the file
            (workspace / "important.py").unlink()
            self.assertFalse((workspace / "important.py").exists())

            result = store.restore_checkpoint(ckpt_id, workspace)
            self.assertTrue((workspace / "important.py").exists())
            self.assertEqual(_read(workspace, "important.py"), "important")
            self.assertEqual(result["restored"], 1)

    def test_unchanged_file_untouched(self) -> None:
        """Files whose content matches the checkpoint should not be rewritten."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            _write(workspace, "same.py", "same content")
            ckpt_id = store.create_checkpoint(workspace, session_id="s1", turn_index=0)

            result = store.restore_checkpoint(ckpt_id, workspace)
            self.assertEqual(result["unchanged"], 1)
            self.assertEqual(result["restored"], 0)
            self.assertEqual(result["removed"], 0)

    def test_unknown_checkpoint_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_ckpt(tmp)
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            with self.assertRaises(FileNotFoundError):
                store.restore_checkpoint("ckpt_nonexistent", workspace)


# ---------------------------------------------------------------------------
# 4. Session store checkpoint cross-references
# ---------------------------------------------------------------------------

class TestSessionStoreCheckpoints(unittest.TestCase):
    def _setup(self, tmp: str):
        store = _make_store(tmp)
        self.addCleanup(store.close)
        sid = store.create_session(working_dir="/proj")
        ckpt = _make_ckpt(tmp)
        return store, sid, ckpt

    def test_save_checkpoint_persists_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, sid, _ = self._setup(tmp)
            store.save_checkpoint(sid, "ckpt_abc", turn_index=0)
            rows = store.list_checkpoints_for_session(sid)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["checkpoint_id"], "ckpt_abc")

    def test_list_checkpoints_ordered_desc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, sid, _ = self._setup(tmp)
            store.save_checkpoint(sid, "ckpt_first", turn_index=0)
            store.save_checkpoint(sid, "ckpt_second", turn_index=1)
            store.save_checkpoint(sid, "ckpt_third", turn_index=2)
            rows = store.list_checkpoints_for_session(sid)
            self.assertEqual(rows[0]["turn_index"], 2)
            self.assertEqual(rows[1]["turn_index"], 1)
            self.assertEqual(rows[2]["turn_index"], 0)

    def test_get_checkpoint_offset_1_returns_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, sid, _ = self._setup(tmp)
            store.save_checkpoint(sid, "ckpt_t0", turn_index=0)
            store.save_checkpoint(sid, "ckpt_t1", turn_index=1)
            result = store.get_checkpoint_at_turn(sid, turn_offset=1)
            self.assertEqual(result, "ckpt_t1")

    def test_get_checkpoint_offset_2_returns_previous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, sid, _ = self._setup(tmp)
            store.save_checkpoint(sid, "ckpt_t0", turn_index=0)
            store.save_checkpoint(sid, "ckpt_t1", turn_index=1)
            result = store.get_checkpoint_at_turn(sid, turn_offset=2)
            self.assertEqual(result, "ckpt_t0")

    def test_get_checkpoint_beyond_depth_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, sid, _ = self._setup(tmp)
            store.save_checkpoint(sid, "ckpt_t0", turn_index=0)
            result = store.get_checkpoint_at_turn(sid, turn_offset=5)
            self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. Multi-turn restore integration
# ---------------------------------------------------------------------------

class TestMultiTurnRestore(unittest.TestCase):
    def test_three_turn_sequence(self) -> None:
        """Verify that each turn's checkpoint correctly restores its own state."""
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_store = _make_ckpt(tmp)
            session_store = _make_store(tmp)
            self.addCleanup(session_store.close)

            sid = session_store.create_session(working_dir="/project")
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()

            # ---- Turn 0: write initial version of main.py ----
            _write(workspace, "main.py", "version = 1")
            ckpt0 = ckpt_store.create_checkpoint(workspace, sid, turn_index=0)
            session_store.save_checkpoint(sid, ckpt0, turn_index=0)

            # ---- Turn 1: edit main.py, add helper.py ----
            _write(workspace, "main.py", "version = 2")
            _write(workspace, "helper.py", "def help(): pass")
            ckpt1 = ckpt_store.create_checkpoint(workspace, sid, turn_index=1)
            session_store.save_checkpoint(sid, ckpt1, turn_index=1)

            # ---- Turn 2: delete helper.py, add new.py ----
            (workspace / "helper.py").unlink()
            _write(workspace, "new.py", "new = True")
            ckpt2 = ckpt_store.create_checkpoint(workspace, sid, turn_index=2)
            session_store.save_checkpoint(sid, ckpt2, turn_index=2)

            # --- /undo 1: restore to state captured in ckpt2 (most recent checkpoint) ---
            ckpt_id = session_store.get_checkpoint_at_turn(sid, turn_offset=1)
            self.assertEqual(ckpt_id, ckpt2)
            ckpt_store.restore_checkpoint(ckpt_id, workspace)
            # ckpt2 captured: main.py="version 2", helper.py gone, new.py present
            self.assertEqual(_read(workspace, "main.py"), "version = 2")
            self.assertFalse((workspace / "helper.py").exists())
            self.assertTrue((workspace / "new.py").exists())

            # --- /undo 2 (cumulative offset=2): restore to ckpt1 state ---
            ckpt_id = session_store.get_checkpoint_at_turn(sid, turn_offset=2)
            self.assertEqual(ckpt_id, ckpt1)
            ckpt_store.restore_checkpoint(ckpt_id, workspace)
            # ckpt1 captured: main.py="version 2", helper.py present, new.py absent
            self.assertEqual(_read(workspace, "main.py"), "version = 2")
            self.assertTrue((workspace / "helper.py").exists())
            self.assertFalse((workspace / "new.py").exists())

            # --- /undo 3 (cumulative offset=3): restore to ckpt0 state ---
            ckpt_id = session_store.get_checkpoint_at_turn(sid, turn_offset=3)
            self.assertEqual(ckpt_id, ckpt0)
            ckpt_store.restore_checkpoint(ckpt_id, workspace)
            # ckpt0 captured: only main.py="version 1"
            self.assertEqual(_read(workspace, "main.py"), "version = 1")
            self.assertFalse((workspace / "helper.py").exists())
            self.assertFalse((workspace / "new.py").exists())


if __name__ == "__main__":
    unittest.main()
