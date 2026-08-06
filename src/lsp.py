"""LSP integration bridge for Hamster.

Provides two layers of language-server access:

1. **LSPDaemon** — a persistent JSON-RPC 2.0 client that keeps a
   ``pyright-langserver --stdio`` process alive between calls.  A background
   reader thread drains the server's stdout and dispatches responses to the
   waiting request threads via per-request queues.  This avoids the
   process-startup overhead on every diagnostic call.

2. **LSPBridge** — the original lightweight shim that falls back gracefully
   to the subprocess-per-call approach when:
   - No LSP server binary is found on PATH
   - The persistent daemon fails to start or dies mid-session
   - Any individual request times out

Both layers share the same :class:`Diagnostic` dataclass as the public result
type so callers need not care which path is taken.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class Diagnostic:
    path: str
    line: int
    column: int
    message: str
    severity: str = "warning"


# ---------------------------------------------------------------------------
# Persistent JSON-RPC LSP daemon
# ---------------------------------------------------------------------------

class LSPDaemon:
    """Persistent JSON-RPC 2.0 LSP server process manager.

    Manages a single long-running language server process (e.g.
    ``pyright-langserver --stdio``) and provides synchronous
    request/response over its stdin/stdout pipe.

    A background reader thread drains stdout and dispatches responses to
    waiting callers via per-request :class:`queue.Queue` instances,
    allowing multiple callers to interleave requests without blocking each
    other on I/O.

    Usage::

        daemon = LSPDaemon(["pyright-langserver", "--stdio"])
        if daemon.start(root_uri="file:///path/to/project"):
            daemon.open_document("/path/to/project/foo.py")
            diags = daemon.get_diagnostics("/path/to/project/foo.py")
            daemon.stop()
    """

    def __init__(self, cmd: list[str]) -> None:
        self._cmd = cmd
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any] | None]] = {}
        self._reader: threading.Thread | None = None
        self._active = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, root_uri: str = "file:///workspace") -> bool:
        """Start the server and perform LSP ``initialize`` handshake.

        Returns ``True`` on success, ``False`` if the server binary is not
        found or the initialize request times out.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True  # already running
            try:
                self._proc = subprocess.Popen(
                    self._cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                return False

            self._active = True
            self._reader = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="lsp-reader",
            )
            self._reader.start()

        # initialize request (sent outside the lock so the reader thread can run)
        result = self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {
                    "textDocument": {
                        "hover": {"contentFormat": ["plaintext"]},
                        "definition": {},
                        "publishDiagnostics": {},
                    }
                },
            },
            timeout=10.0,
        )
        if result is None:
            self.stop()
            return False

        self._notify("initialized", {})
        return True

    def stop(self) -> None:
        """Terminate the server process and unblock any waiting requests."""
        self._active = False
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None

        with self._lock:
            for q in self._pending.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self._pending.clear()

    @property
    def is_running(self) -> bool:
        """True if the server process is alive."""
        return self._active and self._proc is not None and self._proc.poll() is None

    # ------------------------------------------------------------------
    # Background reader thread
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        """Drain LSP stdout and dispatch response messages to waiting callers."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        while self._active:
            try:
                msg = self._read_message(proc.stdout)
                if msg is None:
                    break
                msg_id = msg.get("id")
                if msg_id is not None:
                    with self._lock:
                        pending_q = self._pending.get(msg_id)
                    if pending_q is not None:
                        try:
                            pending_q.put_nowait(msg)
                        except queue.Full:
                            pass
                # Notifications (no ``id`` field) are silently discarded
            except Exception:
                break

        # Unblock all waiters on connection loss
        with self._lock:
            for q in self._pending.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass
            self._pending.clear()

    @staticmethod
    def _read_message(stdout: Any) -> dict[str, Any] | None:
        """Read one JSON-RPC message from *stdout* (Content-Length framed)."""
        header_bytes = b""
        while not header_bytes.endswith(b"\r\n\r\n"):
            ch = stdout.read(1)
            if not ch:
                return None
            header_bytes += ch

        content_length: int | None = None
        for line in header_bytes.decode("ascii", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
                break

        if content_length is None:
            return None

        body = b""
        while len(body) < content_length:
            chunk = stdout.read(content_length - len(body))
            if not chunk:
                return None
            body += chunk

        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _write_message(self, payload: dict[str, Any]) -> bool:
        """Write one JSON-RPC message to the server's stdin."""
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        try:
            body = json.dumps(payload).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            proc.stdin.write(header + body)
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    # ------------------------------------------------------------------
    # Request / notify helpers
    # ------------------------------------------------------------------

    def _request(
        self, method: str, params: dict[str, Any], timeout: float = 5.0
    ) -> dict[str, Any] | None:
        """Send a JSON-RPC request and block until the response arrives."""
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            resp_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1)
            self._pending[req_id] = resp_queue

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        if not self._write_message(payload):
            with self._lock:
                self._pending.pop(req_id, None)
            return None

        try:
            response = resp_queue.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(req_id, None)
            return None
        finally:
            with self._lock:
                self._pending.pop(req_id, None)

        if response is None:
            return None
        return response.get("result")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    # ------------------------------------------------------------------
    # Public LSP operations
    # ------------------------------------------------------------------

    def open_document(self, filepath: str, language_id: str = "python") -> None:
        """Notify the server that a document has been opened."""
        path = Path(filepath)
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self._notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path.as_uri(),
                    "languageId": language_id,
                    "version": 1,
                    "text": text,
                }
            },
        )

    def get_diagnostics(self, filepath: str) -> list[Diagnostic]:
        """Request pull-based diagnostics for *filepath*."""
        path = Path(filepath)
        result = self._request(
            "textDocument/diagnostic",
            {"textDocument": {"uri": path.as_uri()}},
            timeout=15.0,
        )
        if not result:
            return []

        diagnostics: list[Diagnostic] = []
        for item in result.get("items", []):
            rng = item.get("range", {}).get("start", {})
            sev_int = item.get("severity", 2)
            severity = "error" if sev_int == 1 else "warning"
            diagnostics.append(
                Diagnostic(
                    path=filepath,
                    line=rng.get("line", 0) + 1,
                    column=rng.get("character", 0) + 1,
                    message=str(item.get("message", "")),
                    severity=severity,
                )
            )
        return diagnostics


# ---------------------------------------------------------------------------
# Lazy module-level daemon singleton
# ---------------------------------------------------------------------------

_daemon: LSPDaemon | None = None
_daemon_start_attempted = False


def _get_daemon(server_name: str = "pyright-langserver") -> LSPDaemon | None:
    """Return the module-level :class:`LSPDaemon`, starting it lazily.

    Returns ``None`` when the server binary is not found or the daemon fails
    to start, so callers can fall through to the subprocess-per-call approach.
    """
    global _daemon, _daemon_start_attempted
    if _daemon_start_attempted:
        return _daemon if (_daemon is not None and _daemon.is_running) else None

    _daemon_start_attempted = True
    server_path = shutil.which(server_name) or shutil.which("pyright-langserver")
    if server_path is None:
        return None

    _daemon = LSPDaemon(cmd=[server_path, "--stdio"])
    if not _daemon.start():
        _daemon = None
    return _daemon


# ---------------------------------------------------------------------------
# Original lightweight bridge (subprocess-per-call fallback)
# ---------------------------------------------------------------------------

class LSPBridge:
    """Utility hook for optional local language-server inspection.

    Tries the persistent :class:`LSPDaemon` first.  Falls back to the
    original subprocess-per-call approach when the daemon is unavailable or
    the request fails.  This module intentionally stays lightweight and does
    not add any new *required* runtime dependency.
    """

    def __init__(self, server_name: str = "pyright") -> None:
        self.server_name = server_name
        self.server_path = shutil.which(server_name)

    def available(self) -> bool:
        return self.server_path is not None

    def diagnostics(self, filepath: str) -> list[Diagnostic]:
        # 1. Try persistent daemon
        daemon = _get_daemon(self.server_name)
        if daemon is not None:
            daemon.open_document(filepath)
            results = daemon.get_diagnostics(filepath)
            if results:
                return results

        # 2. Subprocess-per-call fallback
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
        """Look up the definition of *symbol* in *filepath*.

        Resolution order:

        1. **AST index** (:mod:`src.ast_index`) using Tree-sitter (when
           installed) or the built-in regex scanner.  Returns definition line,
           column, kind (function / class / assignment), and docstring.
        2. **Original regex scan** of the file — simple ``def``/``class``
           keyword search as a final fallback.
        3. **Unavailable** response when no match is found anywhere.
        """
        # --- 1. AST index (Tree-sitter or regex backend) -----------------
        try:
            from src.ast_index import ASTIndex   # type: ignore[import]
            index = ASTIndex.from_file(filepath)
            defs = index.definitions(symbol)
            if defs:
                return {
                    "status": "resolved",
                    "server": f"ast_index/{index.backend}",
                    "symbol": symbol,
                    "matches": [
                        {
                            "line": d.line,
                            "column": d.column,
                            "kind": d.kind,
                            "docstring": (d.docstring[:200] + "…") if len(d.docstring) > 200 else d.docstring,
                        }
                        for d in defs
                    ],
                }
        except Exception:
            pass

        # --- 2. Keyword-scan fallback (original behaviour) ---------------
        target = Path(filepath).resolve()
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        matches: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if f"def {symbol}" in line or f"class {symbol}" in line:
                matches.append({"line": line_number, "column": line.find(symbol) + 1, "kind": "unknown"})

        if matches:
            return {
                "status": "resolved",
                "server": "keyword_scan",
                "symbol": symbol,
                "matches": matches,
            }

        # --- 3. Not found -------------------------------------------------
        return {
            "status": "unresolved",
            "server": self.server_name,
            "symbol": symbol,
            "message": f"No definition found for {symbol!r} in {filepath!r}.",
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
            diagnostics.append(
                Diagnostic(path=path, line=max(1, line_no), column=1, message=remainder, severity=severity)
            )
        return diagnostics


# ---------------------------------------------------------------------------
# Public module-level helpers
# ---------------------------------------------------------------------------

def parse_local_diagnostics(filepath: str) -> list[Diagnostic]:
    return LSPBridge().diagnostics(filepath)


def resolve_symbol_definition(filepath: str, symbol: str) -> dict[str, Any]:
    return LSPBridge().definition_lookup(filepath, symbol)
