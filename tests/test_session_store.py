"""Unit tests for hamster.session_store.SessionStore.

Each test uses a temporary directory for the SQLite database so it never
touches the user's real ~/.hamster/sessions.db and leaves no artifacts behind.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from hamster.session_store import SessionStore


def _make_store(tmp_dir: str) -> SessionStore:
    """Return a fresh SessionStore backed by a temp-dir DB."""
    return SessionStore(path=Path(tmp_dir) / "sessions.db")


class TestSessionCreation(unittest.TestCase):
    """Tests for create_session and basic session metadata."""

    def test_create_session_returns_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session(working_dir="/tmp/project")
            self.assertIsInstance(sid, str)
            self.assertTrue(len(sid) > 0)

    def test_created_session_appears_in_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session(working_dir="/tmp/project")
            sessions = store.list_sessions()
            ids = [s["session_id"] for s in sessions]
            self.assertIn(sid, ids)

    def test_create_multiple_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid1 = store.create_session(working_dir="/a")
            sid2 = store.create_session(working_dir="/b")
            sessions = store.list_sessions()
            ids = [s["session_id"] for s in sessions]
            self.assertIn(sid1, ids)
            self.assertIn(sid2, ids)
            self.assertEqual(len(sessions), 2)

    def test_session_ids_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            ids = {store.create_session() for _ in range(20)}
            self.assertEqual(len(ids), 20)


class TestGetAndDelete(unittest.TestCase):
    """Tests for get_session and delete_session."""

    def test_get_session_returns_correct_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session(working_dir="/myproject")
            row = store.get_session(sid)
            self.assertIsNotNone(row)
            self.assertEqual(row["session_id"], sid)
            self.assertEqual(row["working_dir"], "/myproject")

    def test_get_session_unknown_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            self.assertIsNone(store.get_session("nonexistent_id"))

    def test_delete_session_removes_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.delete_session(sid)
            self.assertIsNone(store.get_session(sid))
            self.assertEqual(store.list_sessions(), [])

    def test_delete_session_cascades_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.save_message(sid, {"role": "user", "content": "hello"})
            store.delete_session(sid)
            # Messages table should be empty after cascade
            msgs = store.load_messages(sid)
            self.assertEqual(msgs, [])


class TestUpdateMeta(unittest.TestCase):
    """Tests for update_meta."""

    def test_update_meta_persists_last_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.update_meta(sid, last_prompt="What is 2+2?", token_usage=5)
            row = store.get_session(sid)
            self.assertEqual(row["last_prompt"], "What is 2+2?")

    def test_token_usage_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.update_meta(sid, last_prompt="q", token_usage=42)
            row = store.get_session(sid)
            self.assertEqual(row["token_usage"], 42)

    def test_update_meta_bumps_updated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            before = store.get_session(sid)["updated_at"]
            time.sleep(1.01)  # ensure clock ticks at least 1 second
            store.update_meta(sid, last_prompt="bump")
            after = store.get_session(sid)["updated_at"]
            self.assertGreater(after, before)


class TestMessagePersistence(unittest.TestCase):
    """Tests for save_message, save_messages, and load_messages."""

    def test_save_and_load_single_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.save_message(sid, {"role": "user", "content": "Hello"})
            msgs = store.load_messages(sid)
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0]["role"], "user")
            self.assertEqual(msgs[0]["content"], "Hello")

    def test_message_order_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            turns = [
                {"role": "system", "content": "You are Hamster."},
                {"role": "user", "content": "Turn 1"},
                {"role": "assistant", "content": "Response 1"},
                {"role": "user", "content": "Turn 2"},
                {"role": "assistant", "content": "Response 2"},
            ]
            for msg in turns:
                store.save_message(sid, msg)
            loaded = store.load_messages(sid)
            self.assertEqual(len(loaded), len(turns))
            for original, restored in zip(turns, loaded):
                self.assertEqual(original["role"], restored["role"])
                self.assertEqual(original["content"], restored["content"])

    def test_save_messages_bulk_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hey"},
            ]
            store.save_messages(sid, messages)
            loaded = store.load_messages(sid)
            self.assertEqual(len(loaded), 3)
            self.assertEqual(loaded[0]["content"], "sys")
            self.assertEqual(loaded[1]["content"], "hi")
            self.assertEqual(loaded[2]["content"], "hey")

    def test_save_messages_replaces_existing(self) -> None:
        """save_messages should be idempotent — calling it twice keeps only the latest list."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            store.save_messages(sid, [{"role": "user", "content": "first"}])
            store.save_messages(sid, [{"role": "user", "content": "second"}])
            loaded = store.load_messages(sid)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["content"], "second")

    def test_tool_message_roundtrip(self) -> None:
        """Tool result messages should preserve tool_name and tool_call_id."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid = store.create_session()
            tool_msg = {
                "role": "tool",
                "content": "File written successfully.",
                "name": "write_file",
                "tool_call_id": "call_abc123",
            }
            store.save_message(sid, tool_msg)
            loaded = store.load_messages(sid)
            self.assertEqual(len(loaded), 1)
            m = loaded[0]
            self.assertEqual(m["role"], "tool")
            self.assertEqual(m["content"], "File written successfully.")
            self.assertEqual(m["name"], "write_file")
            self.assertEqual(m["tool_call_id"], "call_abc123")

    def test_resume_restores_full_conversation(self) -> None:
        """Full resume cycle: save messages, close store, reopen, load messages."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "sessions.db"

            # Simulate a session
            store1 = SessionStore(path=db_path)
            sid = store1.create_session(working_dir="/proj")
            conversation = [
                {"role": "system", "content": "You are Hamster."},
                {"role": "user", "content": "Refactor utils.py"},
                {"role": "assistant", "content": "Sure, I'll start by reading the file."},
                {"role": "user", "content": "Looks good, apply it."},
                {"role": "assistant", "content": "Done!"},
            ]
            store1.save_messages(sid, conversation)
            store1.update_meta(sid, last_prompt="Looks good, apply it.", token_usage=5)
            store1.close()

            # Simulate reopening in a new process
            store2 = SessionStore(path=db_path)
            row = store2.get_session(sid)
            self.assertIsNotNone(row)
            self.assertEqual(row["working_dir"], "/proj")
            self.assertEqual(row["last_prompt"], "Looks good, apply it.")

            loaded = store2.load_messages(sid)
            self.assertEqual(len(loaded), len(conversation))
            for orig, restored in zip(conversation, loaded):
                self.assertEqual(orig["role"], restored["role"])
                self.assertEqual(orig["content"], restored["content"])
            store2.close()


class TestListSessions(unittest.TestCase):
    """Tests for list_sessions ordering guarantee."""

    def test_list_sessions_newest_first(self) -> None:
        """Sessions should be returned with the most-recently-updated first."""
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            sid1 = store.create_session(working_dir="/old")
            time.sleep(1.01)
            sid2 = store.create_session(working_dir="/new")
            # Touch sid2 to make it clearly the newest
            store.update_meta(sid2, last_prompt="latest")
            sessions = store.list_sessions()
            self.assertEqual(sessions[0]["session_id"], sid2)
            self.assertEqual(sessions[1]["session_id"], sid1)

    def test_list_sessions_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            self.addCleanup(store.close)
            self.assertEqual(store.list_sessions(), [])


if __name__ == "__main__":
    unittest.main()
