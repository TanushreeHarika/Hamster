"""hamster.auth.oauth — Google OAuth 2.0 PKCE flow (stdlib-only core).

All cryptographic and HTTP operations use the Python standard library
(``hashlib``, ``base64``, ``secrets``, ``urllib``, ``webbrowser``).
No third-party packages are imported from this module.

Typical usage::

    flow = AuthFlow(client_id="...", client_secret="...")
    token_data = flow.run()          # opens browser, blocks until callback
    # token_data keys: access_token, refresh_token, id_token, expires_in
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Any

from hamster.auth.server import REDIRECT_URI, SingleRequestHTTPServer


# ---------------------------------------------------------------------------
# Google OAuth 2.0 endpoints
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"
OAUTH_SCOPES      = "openid email profile"


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PKCEParams:
    """Immutable PKCE parameter pair."""
    code_verifier: str
    code_challenge: str


def generate_pkce_params() -> PKCEParams:
    """Generate a cryptographically secure PKCE verifier + SHA-256 challenge.

    The verifier uses 96 random bytes (128 base64url chars, no padding) which
    satisfies the RFC 7636 requirement of 43–128 characters.  The challenge is
    the base64url-encoded (no padding) SHA-256 digest of the verifier bytes.
    """
    # 96 bytes → 128 base64url chars (no padding)
    verifier_bytes = secrets.token_bytes(96)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")

    # S256 challenge: BASE64URL(SHA256(ASCII(verifier)))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return PKCEParams(code_verifier=code_verifier, code_challenge=code_challenge)


def generate_state() -> str:
    """Return a cryptographically random CSRF state token (32 URL-safe chars min)."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------

def build_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    pkce: PKCEParams,
    scopes: str = OAUTH_SCOPES,
) -> str:
    """Construct the Google OAuth 2.0 authorization URL with PKCE parameters.

    Args:
        client_id:    Google OAuth 2.0 Client ID.
        redirect_uri: Must match one of the authorized redirect URIs in the
                      Google Cloud Console project.
        state:        CSRF state token (opaque, verified on callback).
        pkce:         Pre-generated PKCE parameter pair.
        scopes:       Space-separated OAuth 2.0 scopes.

    Returns:
        Fully-formed authorization URL ready to open in the user's browser.
    """
    params = {
        "client_id":             client_id,
        "redirect_uri":          redirect_uri,
        "response_type":         "code",
        "scope":                 scopes,
        "state":                 state,
        "code_challenge":        pkce.code_challenge,
        "code_challenge_method": "S256",
        "access_type":           "offline",  # request refresh_token
        "prompt":                "consent",  # force consent so refresh_token is always returned
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

def exchange_code(
    *,
    code: str,
    code_verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """POST to Google's token endpoint to exchange an authorization code for tokens.

    Uses ``urllib.request`` (stdlib) so no third-party HTTP library is required
    in the critical path.

    Args:
        code:          Authorization code received from the callback.
        code_verifier: The raw PKCE verifier (not the challenge).
        client_id:     Google OAuth 2.0 Client ID.
        client_secret: Google OAuth 2.0 Client Secret.
        redirect_uri:  Must exactly match the one used in the authorization request.

    Returns:
        Parsed JSON response dict containing at least:
        ``access_token``, ``token_type``, ``expires_in``, ``id_token``.
        ``refresh_token`` is included when ``prompt=consent`` was set.

    Raises:
        RuntimeError: If the token endpoint returns a non-200 response.
    """
    payload = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  redirect_uri,
        "client_id":     client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }).encode("ascii")

    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Token exchange failed: HTTP {exc.code}. "
            f"Response: {error_body}"
        ) from exc

    return json.loads(body)


# ---------------------------------------------------------------------------
# High-level orchestrator
# ---------------------------------------------------------------------------

class AuthFlow:
    """Full PKCE + OAuth 2.0 authorization flow orchestrator.

    Opens the user's browser to the Google consent screen, spins up a
    short-lived local HTTP server to receive the callback, and then
    exchanges the authorization code for tokens.

    Args:
        client_id:     Google OAuth 2.0 Client ID (from ``GOOGLE_CLIENT_ID``).
        client_secret: Google OAuth 2.0 Client Secret (from ``GOOGLE_CLIENT_SECRET``).
        redirect_uri:  Local callback URI (default: ``http://127.0.0.1:8080/callback``).
        timeout:       Seconds to wait for the browser callback (default: 120).

    Example::

        flow = AuthFlow(client_id="...", client_secret="...")
        tokens = flow.run()
        print(tokens["access_token"])
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = REDIRECT_URI,
        timeout: int = 120,
    ) -> None:
        if not client_id:
            raise ValueError(
                "GOOGLE_CLIENT_ID is not set. "
                "Add it to your .env file to use `hamster login`."
            )
        if not client_secret:
            raise ValueError(
                "GOOGLE_CLIENT_SECRET is not set. "
                "Add it to your .env file to use `hamster login`."
            )
        self.client_id     = client_id
        self.client_secret = client_secret
        self.redirect_uri  = redirect_uri
        self.timeout       = timeout

    def run(self) -> dict[str, Any]:
        """Execute the full PKCE login flow and return the token dictionary.

        Steps:
        1. Generate PKCE params and CSRF state.
        2. Build and open the authorization URL in the default browser.
        3. Listen on ``127.0.0.1:8080`` for the OAuth callback.
        4. Verify state, extract authorization code.
        5. POST to the token endpoint and return the response.

        Returns:
            Token dict with keys: ``access_token``, ``refresh_token``,
            ``id_token``, ``token_type``, ``expires_in``.

        Raises:
            RuntimeError: On state mismatch, server timeout, or token exchange failure.
        """
        pkce  = generate_pkce_params()
        state = generate_state()
        auth_url = build_auth_url(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            state=state,
            pkce=pkce,
        )

        print(f"\n🔗  Opening browser for Google login…")
        print(f"   If it doesn't open automatically, visit:\n   {auth_url}\n")
        webbrowser.open(auth_url)

        # Block until callback received or timeout
        with SingleRequestHTTPServer(expected_state=state) as srv:
            result = srv.handle_one_request(timeout=self.timeout)

        if result is None:
            raise RuntimeError(
                f"OAuth callback timed out after {self.timeout}s. "
                "Make sure 127.0.0.1:8080 is reachable and try again."
            )

        code = result["code"]
        return exchange_code(
            code=code,
            code_verifier=pkce.code_verifier,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
        )
