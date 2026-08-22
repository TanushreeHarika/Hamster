"""Persistent session store for Hamster.

Stores conversation history, session metadata, and token usage in a local
SQLite database so sessions can be resumed after the CLI exits.

Database location: ``~/.hamster/sessions.db`` (created automatically).

Schema
------
``sessions`` table
    session_id   TEXT PRIMARY KEY
    working_dir  TEXT NOT NULL
    created_at   TEXT NOT NULL   -- ISO-8601 UTC
    updated_at   TEXT NOT NULL   -- ISO-8601 UTC
    last_prompt  TEXT            -- excerpt of most recent user turn
    token_usage  INTEGER NOT NULL DEFAULT 0

``messages`` table
    id           INTEGER PRIMARY KEY AUTOINCREMENT
    session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE
    role         TEXT NOT NULL   -- "system" | "user" | "assistant" | "tool"
    content      TEXT            -- text content of the message
    tool_name    TEXT            -- present for role="tool" messages
    tool_call_id TEXT            -- present for role="tool" messages
    inserted_at  TEXT NOT NULL   -- ISO-8601 UTC

Public API
----------
::

    store = SessionStore()                         # or SessionStore(path=Path("custom.db"))

    sid   = store.create_session(working_dir)      # returns session_id str
    store.save_message(sid, msg_dict)              # append one OpenRouter message dict
    store.save_messages(sid, messages)             # bulk-save entire message list
    msgs  = store.load_messages(sid)               # reconstruct messages list
    store.update_meta(sid, last_prompt, tokens)    # update last_prompt + token_usage
    rows  = store.list_sessions()                  # list[dict], newest first
    row   = store.get_session(sid)                 # dict | None
    store.delete_session(sid)                      # hard-delete session + messages
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Default DB path — created in the user's home directory under ~/.hamster/
DEFAULT_DB_PATH: Path = Path.home() / ".hamster" / "sessions.db"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string (no microseconds)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SessionStore:
    """SQLite-backed persistent session store.

    Creates the database and schema on first use.  Thread-safe through the
    ``check_same_thread=False`` connection flag combined with the serialised
    Python GIL (Hamster is single-threaded in the CLI path).

    Args:
        path: Path to the SQLite database file.  Defaults to
              ``~/.hamster/sessions.db``.  The parent directory is created
              automatically if it does not exist.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    # ------------------------------------------------------------------
    # Schema creation / migration
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        """Create tables if they don't exist (idempotent)."""
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                working_dir  TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                last_prompt  TEXT,
                token_usage  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT NOT NULL
                             REFERENCES sessions(session_id) ON DELETE CASCADE,
                role         TEXT NOT NULL,
                content      TEXT,
                tool_name    TEXT,
                tool_call_id TEXT,
                inserted_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id  TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL
                               REFERENCES sessions(session_id) ON DELETE CASCADE,
                turn_index     INTEGER NOT NULL,
                created_at     TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_checkpoints_session
                ON checkpoints(session_id, turn_index);
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, working_dir: str | Path = "") -> str:
        """Create a new session row and return its ``session_id``.

        Args:
            working_dir: The project root path for this session (informational).

        Returns:
            A short random hex ``session_id`` string.
        """
        session_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO sessions (session_id, working_dir, created_at, updated_at, last_prompt, token_usage)
            VALUES (?, ?, ?, ?, NULL, 0)
            """,
            (session_id, str(working_dir), now, now),
        )
        self._conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return the sessions row as a dict, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return all sessions ordered by ``updated_at`` descending (newest first)."""
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_meta(
        self,
        session_id: str,
        last_prompt: str | None = None,
        token_usage: int = 0,
    ) -> None:
        """Update ``updated_at``, ``last_prompt``, and ``token_usage`` for a session.

        Args:
            session_id:  Target session.
            last_prompt: Excerpt of the most recent user turn (optional).
            token_usage: Total token count to store (cumulative, not delta).
        """
        self._conn.execute(
            """
            UPDATE sessions
            SET updated_at = ?, last_prompt = ?, token_usage = ?
            WHERE session_id = ?
            """,
            (_now_iso(), last_prompt, token_usage, session_id),
        )
        self._conn.commit()

    def delete_session(self, session_id: str) -> None:
        """Hard-delete a session and all its messages (cascades via FK)."""
        self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Message persistence
    # ------------------------------------------------------------------

    def save_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Append a single OpenRouter-format message dict to the store.

        Supported roles: ``system``, ``user``, ``assistant``, ``tool``.
        The ``content`` field may be a string or a list; lists are
        JSON-serialised before storage.

        Args:
            session_id: Target session.
            message:    A dict with at least ``role`` and ``content`` keys,
                        plus optional ``name`` / ``tool_call_id`` for tool
                        result messages.
        """
        role = message.get("role", "")
        content = message.get("content")
        if isinstance(content, list):
            content = json.dumps(content)
        tool_name = message.get("name")
        tool_call_id = message.get("tool_call_id")
        self._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, tool_name, tool_call_id, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, content, tool_name, tool_call_id, _now_iso()),
        )
        self._conn.commit()

    def save_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Bulk-save an entire message list, replacing any existing messages.

        Deletes all existing messages for the session first, then re-inserts
        the full list in order.  This keeps ``load_messages`` consistent with
        the in-memory ``messages`` list after every agent turn.

        Args:
            session_id: Target session.
            messages:   Full message list (including the system prompt).
        """
        now = _now_iso()
        # Clear existing rows for this session before re-inserting
        self._conn.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,)
        )
        rows = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content")
            if isinstance(content, list):
                content = json.dumps(content)
            tool_name = msg.get("name")
            tool_call_id = msg.get("tool_call_id")
            rows.append((session_id, role, content, tool_name, tool_call_id, now))
        self._conn.executemany(
            """
            INSERT INTO messages (session_id, role, content, tool_name, tool_call_id, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def load_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Load all messages for a session in insertion order.

        Reconstructs OpenRouter-format message dicts suitable for passing
        directly to :func:`hamster.agent.run_agent_turn`.

        Args:
            session_id: Target session.

        Returns:
            List of message dicts, ordered by insertion (ascending ``id``).
        """
        rows = self._conn.execute(
            """
            SELECT role, content, tool_name, tool_call_id
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ).fetchall()

        messages: list[dict[str, Any]] = []
        for row in rows:
            role = row["role"]
            raw_content = row["content"]

            # Attempt to deserialise JSON-encoded list content
            content: Any = raw_content
            if raw_content and raw_content.startswith("["):
                try:
                    content = json.loads(raw_content)
                except json.JSONDecodeError:
                    pass

            msg: dict[str, Any] = {"role": role, "content": content}
            if row["tool_name"]:
                msg["name"] = row["tool_name"]
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            messages.append(msg)
        return messages

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Checkpoint cross-references
    # ------------------------------------------------------------------

    def save_checkpoint(
        self,
        session_id: str,
        checkpoint_id: str,
        turn_index: int,
    ) -> None:
        """Persist a checkpoint cross-reference for a session turn.

        Args:
            session_id:    The active session.
            checkpoint_id: The CAS checkpoint identifier returned by
                           :class:`hamster.checkpoint.CheckpointStore`.
            turn_index:    Which user turn this checkpoint was taken before.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO checkpoints (checkpoint_id, session_id, turn_index, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (checkpoint_id, session_id, turn_index, _now_iso()),
        )
        self._conn.commit()

    def list_checkpoints_for_session(
        self, session_id: str
    ) -> list[dict[str, Any]]:
        """Return all checkpoints for *session_id* ordered by turn_index descending.

        The most recent checkpoint (highest turn_index) is first.
        """
        rows = self._conn.execute(
            """
            SELECT checkpoint_id, session_id, turn_index, created_at
            FROM checkpoints
            WHERE session_id = ?
            ORDER BY turn_index DESC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_checkpoint_at_turn(
        self, session_id: str, turn_offset: int = 1
    ) -> str | None:
        """Return the checkpoint_id for ``turn_offset`` turns ago.

        ``turn_offset=1`` → the checkpoint taken just before the last turn.
        ``turn_offset=2`` → the one before that, and so on.

        Returns ``None`` when there are fewer checkpoints than *turn_offset*.

        Args:
            session_id:  The active session.
            turn_offset: How many turns back to look (1 = most recent).
        """
        if turn_offset < 1:
            return None
        rows = self._conn.execute(
            """
            SELECT checkpoint_id
            FROM checkpoints
            WHERE session_id = ?
            ORDER BY turn_index DESC
            LIMIT ?
            """,
            (session_id, turn_offset),
        ).fetchall()
        if len(rows) < turn_offset:
            return None
        return rows[turn_offset - 1]["checkpoint_id"]

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SessionStore(path={self._path!r})"
