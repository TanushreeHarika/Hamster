"""hamster.auth.server — Single-request local HTTP callback server (stdlib-only).

``SingleRequestHTTPServer`` listens on ``127.0.0.1:8080``, handles exactly one
GET request to ``/callback``, extracts ``code`` and ``state`` query parameters,
verifies the CSRF state, serves a user-friendly HTML success page, and then
shuts itself down cleanly.

Usage::

    with SingleRequestHTTPServer(expected_state="abc123") as srv:
        result = srv.handle_one_request(timeout=120)
    # result is {"code": "...", "state": "..."} or None on timeout
"""

from __future__ import annotations

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Self

CALLBACK_PORT = 8080
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"

# Minimal success HTML served to the browser after a successful auth callback.
_SUCCESS_HTML = rb"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hamster \u2014 Login Successful</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:#0d0d0d;color:#f5f5f5;
         display:flex;align-items:center;justify-content:center;min-height:100vh}
    .card{background:#1a1a1a;border:1px solid #2e2e2e;border-radius:12px;
          padding:40px 48px;text-align:center;max-width:480px;width:100%}
    .icon{font-size:64px;margin-bottom:16px}
    h1{font-size:24px;font-weight:700;color:#f5c518;margin-bottom:8px}
    p{color:#aaa;font-size:15px;line-height:1.5}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">\U0001f439</div>
    <h1>Authentication Successful!</h1>
    <p>You\u2019re logged into Hamster CLI.<br>You may safely close this tab.</p>
  </div>
</body>
</html>"""

_ERROR_HTML = rb"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Hamster \u2014 Login Error</title>
  <style>
    body{font-family:system-ui,sans-serif;background:#0d0d0d;color:#f5f5f5;
         display:flex;align-items:center;justify-content:center;min-height:100vh}
    .card{background:#1a1a1a;border:1px solid #500;border-radius:12px;
          padding:40px 48px;text-align:center;max-width:480px;width:100%}
    h1{font-size:22px;color:#e05252;margin-bottom:8px}
    p{color:#aaa;font-size:15px}
  </style>
</head>
<body>
  <div class="card">
    <h1>&#x26A0;&#xFE0F; Authentication Failed</h1>
    <p>State mismatch or missing parameters.<br>Please try <code>hamster login</code> again.</p>
  </div>
</body>
</html>"""


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler that processes a single OAuth 2.0 callback.

    Parses ``?code=…&state=…`` from the GET request, stores the result on
    ``server.callback_result``, and serves the appropriate HTML response.
    Sets ``server.callback_received`` to signal the waiting thread.
    """

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self._respond(404, b"Not Found")
            return

        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self.server.callback_result = {"error": error}
            self._respond(400, _ERROR_HTML, content_type="text/html; charset=utf-8")
            self.server.callback_received.set()
            return

        if not code or not state:
            self.server.callback_result = {"error": "missing_code_or_state"}
            self._respond(400, _ERROR_HTML, content_type="text/html; charset=utf-8")
            self.server.callback_received.set()
            return

        if state != self.server.expected_state:
            self.server.callback_result = {"error": "state_mismatch"}
            self._respond(400, _ERROR_HTML, content_type="text/html; charset=utf-8")
            self.server.callback_received.set()
            return

        self.server.callback_result = {"code": code, "state": state}
        self._respond(200, _SUCCESS_HTML, content_type="text/html; charset=utf-8")
        self.server.callback_received.set()

    def _respond(
        self,
        status: int,
        body: bytes,
        content_type: str = "text/plain",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Suppress default access log output."""


class SingleRequestHTTPServer(HTTPServer):
    """A local HTTP server that handles exactly one OAuth callback then shuts down.

    Attributes:
        expected_state:    CSRF state token to verify against the callback.
        callback_result:   Set by the handler after receiving a request.
        callback_received: ``threading.Event`` signalled when a callback arrives.

    Usage as a context manager::

        with SingleRequestHTTPServer(expected_state="abc") as srv:
            result = srv.handle_one_request(timeout=120)
    """

    allow_reuse_address = True

    def __init__(self, expected_state: str, port: int = CALLBACK_PORT) -> None:
        self.expected_state: str = expected_state
        self.callback_result: dict[str, str] | None = None
        self.callback_received: threading.Event = threading.Event()
        super().__init__(("127.0.0.1", port), OAuthCallbackHandler)
        self.timeout = 1.0  # Allow handle_request() to unblock periodically

    # ---- context manager ----

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.server_close()

    # ---- main blocking call ----

    def handle_one_request(self, timeout: int = 120) -> dict[str, str] | None:
        """Block until one callback arrives or *timeout* seconds elapse.

        Spawns the server in a daemon thread so the main thread can wait on
        ``callback_received``.  Once the event fires the server thread exits
        naturally after the response is sent.

        Args:
            timeout: Maximum seconds to wait for the browser callback.

        Returns:
            ``{"code": "...", "state": "..."}`` on success, or ``None`` on
            timeout / error.

        Raises:
            RuntimeError: If the callback contained a state mismatch or OAuth error.
        """

        def _serve() -> None:
            # Serve requests until the event is set; handle_request uses select
            # internally so this won't block indefinitely.
            while not self.callback_received.is_set():
                self.handle_request()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

        received = self.callback_received.wait(timeout=timeout)
        if not received:
            return None

        result = self.callback_result
        if result is None:
            return None

        if "error" in result:
            raise RuntimeError(
                f"OAuth callback error: {result['error']}. "
                "Please try `hamster login` again."
            )

        return result
