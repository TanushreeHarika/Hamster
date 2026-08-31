"""Tests for hamster.auth — PKCE generation, callback server, token storage, and profile extraction.

All tests are fully isolated: no real browser is opened, no real Google API
calls are made, and no real OS keyring is accessed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. PKCE parameter generation
# ---------------------------------------------------------------------------


class TestPKCEGeneration(unittest.TestCase):
    """Verify PKCE verifier and challenge generation against RFC 7636."""

    def setUp(self):
        from hamster.auth.oauth import generate_pkce_params

        self.pkce = generate_pkce_params()

    def test_verifier_is_string(self):
        self.assertIsInstance(self.pkce.code_verifier, str)

    def test_verifier_length_meets_rfc_minimum(self):
        """RFC 7636 §4.1 requires 43–128 characters."""
        self.assertGreaterEqual(len(self.pkce.code_verifier), 43)
        self.assertLessEqual(len(self.pkce.code_verifier), 128)

    def test_verifier_contains_only_urlsafe_chars(self):
        """Verifier must use unreserved characters: A-Z a-z 0-9 - _ . ~"""
        self.assertRegex(self.pkce.code_verifier, r"^[A-Za-z0-9\-_\.~]+$")

    def test_challenge_is_base64url_no_padding(self):
        """Challenge must NOT contain '+', '/', or '=' (base64url, no padding)."""
        c = self.pkce.code_challenge
        self.assertNotIn("+", c)
        self.assertNotIn("/", c)
        self.assertNotIn("=", c)

    def test_challenge_is_sha256_of_verifier(self):
        """S256 challenge = BASE64URL(SHA256(ASCII(verifier)))."""
        digest = hashlib.sha256(self.pkce.code_verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        self.assertEqual(self.pkce.code_challenge, expected)

    def test_each_call_produces_unique_params(self):
        """PKCE params are generated freshly each time."""
        from hamster.auth.oauth import generate_pkce_params

        other = generate_pkce_params()
        self.assertNotEqual(self.pkce.code_verifier, other.code_verifier)
        self.assertNotEqual(self.pkce.code_challenge, other.code_challenge)


# ---------------------------------------------------------------------------
# 2. State token generation
# ---------------------------------------------------------------------------


class TestStateGeneration(unittest.TestCase):
    def test_state_is_string(self):
        from hamster.auth.oauth import generate_state

        self.assertIsInstance(generate_state(), str)

    def test_state_minimum_length(self):
        """32 bytes → at least 43 base64url chars."""
        from hamster.auth.oauth import generate_state

        self.assertGreaterEqual(len(generate_state()), 43)

    def test_state_uniqueness(self):
        from hamster.auth.oauth import generate_state

        states = {generate_state() for _ in range(20)}
        self.assertEqual(len(states), 20)


# ---------------------------------------------------------------------------
# 3. Authorization URL builder
# ---------------------------------------------------------------------------


class TestBuildAuthUrl(unittest.TestCase):
    def setUp(self):
        from hamster.auth.oauth import (
            build_auth_url,
            generate_pkce_params,
            generate_state,
        )

        self.pkce = generate_pkce_params()
        self.state = generate_state()
        self.url = build_auth_url(
            client_id="test-client-id",
            redirect_uri="http://localhost:8080/callback",
            state=self.state,
            pkce=self.pkce,
        )
        parsed = urllib.parse.urlparse(self.url)
        self.params = urllib.parse.parse_qs(parsed.query)

    def test_base_url_is_google(self):
        self.assertIn("accounts.google.com", self.url)

    def test_client_id_present(self):
        self.assertEqual(self.params["client_id"][0], "test-client-id")

    def test_response_type_is_code(self):
        self.assertEqual(self.params["response_type"][0], "code")

    def test_state_matches(self):
        self.assertEqual(self.params["state"][0], self.state)

    def test_challenge_method_is_s256(self):
        self.assertEqual(self.params["code_challenge_method"][0], "S256")

    def test_challenge_matches_pkce(self):
        self.assertEqual(self.params["code_challenge"][0], self.pkce.code_challenge)

    def test_scopes_include_openid_email_profile(self):
        scopes = self.params["scope"][0].split()
        for scope in ("openid", "email", "profile"):
            self.assertIn(scope, scopes)

    def test_access_type_offline_for_refresh_token(self):
        self.assertEqual(self.params["access_type"][0], "offline")


# ---------------------------------------------------------------------------
# 4. OAuth callback server
# ---------------------------------------------------------------------------


class TestOAuthCallbackHandler(unittest.TestCase):
    """Integration test: spin up the server, hit /callback, verify result."""

    def _find_free_port(self) -> int:
        with socket.socket() as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]

    def test_successful_callback_returns_code_and_state(self):
        from hamster.auth.server import SingleRequestHTTPServer

        expected_state = "test-state-xyz"
        port = self._find_free_port()

        # Override the port in the server class temporarily
        with patch.object(
            SingleRequestHTTPServer,
            "__init__",
            wraps=lambda self_inner, es, p=port: (
                SingleRequestHTTPServer.__bases__[0].__init__(
                    self_inner,
                    ("localhost", port),
                    __import__(
                        "hamster.auth.server", fromlist=["OAuthCallbackHandler"]
                    ).OAuthCallbackHandler,
                )
                or setattr(self_inner, "expected_state", es)
                or setattr(self_inner, "callback_result", None)
                or setattr(
                    self_inner, "callback_received", __import__("threading").Event()
                )
            ),
        ):
            pass  # complex mock; use direct construction below

        # Direct construction bypassing the port patch complexity
        from hamster.auth.server import SingleRequestHTTPServer

        srv = SingleRequestHTTPServer(expected_state=expected_state, port=port)
        result_holder: list[dict | None] = [None]

        def _serve():
            result_holder[0] = srv.handle_one_request(timeout=5)
            srv.server_close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        time.sleep(0.1)  # let server start

        # Simulate the browser callback
        url = f"http://localhost:{port}/callback?code=auth-code-123&state={expected_state}"
        try:
            urllib.request.urlopen(url, timeout=3)
        except (OSError, TimeoutError, ValueError):
            pass  # connection closed after response is fine

        t.join(timeout=6)
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0]["code"], "auth-code-123")
        self.assertEqual(result_holder[0]["state"], expected_state)

    def test_state_mismatch_raises_runtime_error(self):
        from hamster.auth.server import SingleRequestHTTPServer

        port = self._find_free_port()
        srv = SingleRequestHTTPServer(expected_state="correct-state", port=port)

        def _serve():
            with self.assertRaises(RuntimeError):
                srv.handle_one_request(timeout=5)
            srv.server_close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        time.sleep(0.1)

        url = f"http://localhost:{port}/callback?code=x&state=WRONG-STATE"
        try:
            urllib.request.urlopen(url, timeout=3)
        except (OSError, TimeoutError, ValueError):
            pass

        t.join(timeout=6)

    def test_timeout_returns_none(self):
        from hamster.auth.server import SingleRequestHTTPServer

        port = self._find_free_port()
        srv = SingleRequestHTTPServer(expected_state="any-state", port=port)
        result = srv.handle_one_request(timeout=1)
        srv.server_close()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. Secure token store — file fallback
# ---------------------------------------------------------------------------


class TestSecureTokenStoreFileFallback(unittest.TestCase):
    """Test the file-based storage backend (no keyring required)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "auth_session.json"
        from hamster.auth.store import SecureTokenStore

        # Force file-only mode by making keyring always unavailable
        self.store = SecureTokenStore(fallback_path=self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_keyring_unavailable(self):
        """Patch keyring so all backend methods fall through to file."""
        return patch.dict("sys.modules", {"keyring": None})

    def test_file_save_and_load_roundtrip(self):
        payload = {
            "email": "test@example.com",
            "access_token": "tok123",
            "sub": "1234567890",
        }
        with self._make_keyring_unavailable():
            self.store.save(payload)
            loaded = self.store.load()
        self.assertEqual(loaded["email"], "test@example.com")
        self.assertEqual(loaded["access_token"], "tok123")

    def test_file_created_with_0o600_permissions(self):
        payload = {"email": "sec@example.com"}
        with self._make_keyring_unavailable():
            self.store.save(payload)
        mode = oct(stat.S_IMODE(os.stat(self.db_path).st_mode))
        self.assertEqual(mode, oct(0o600))

    def test_file_delete_removes_file(self):
        payload = {"email": "del@example.com"}
        with self._make_keyring_unavailable():
            self.store.save(payload)
            self.assertTrue(self.db_path.exists())
            self.store.delete()
        self.assertFalse(self.db_path.exists())

    def test_load_returns_none_when_file_absent(self):
        with self._make_keyring_unavailable():
            result = self.store.load()
        self.assertIsNone(result)

    def test_delete_is_idempotent_when_file_absent(self):
        with self._make_keyring_unavailable():
            # Should not raise even if file never existed
            self.store.delete()
            self.store.delete()


# ---------------------------------------------------------------------------
# 6. Secure token store — keyring backend (mocked)
# ---------------------------------------------------------------------------


class TestSecureTokenStoreKeyring(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "auth_session.json"
        from hamster.auth.store import SecureTokenStore

        self.store = SecureTokenStore(fallback_path=self.db_path)
        # Set up keyring mock
        self.mock_keyring = MagicMock()
        self.mock_keyring.get_password.return_value = None
        self._storage: dict[str, str] = {}

        def _set_password(service, username, password):
            self._storage[f"{service}:{username}"] = password

        def _get_password(service, username):
            return self._storage.get(f"{service}:{username}")

        def _delete_password(service, username):
            self._storage.pop(f"{service}:{username}", None)

        self.mock_keyring.set_password.side_effect = _set_password
        self.mock_keyring.get_password.side_effect = _get_password
        self.mock_keyring.delete_password.side_effect = _delete_password

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_keyring_save_and_load_roundtrip(self):
        payload = {"email": "kr@example.com", "refresh_token": "rr999"}
        with patch.dict("sys.modules", {"keyring": self.mock_keyring}):
            self.store.save(payload)
            loaded = self.store.load()
        self.assertEqual(loaded["email"], "kr@example.com")
        self.assertEqual(loaded["refresh_token"], "rr999")

    def test_keyring_fallback_on_import_error(self):
        """When keyring raises ImportError, silently write to file instead."""
        payload = {"email": "fallback@example.com"}
        with patch.dict("sys.modules", {"keyring": None}):
            self.store.save(payload)
        # File must have been written
        self.assertTrue(self.db_path.exists())
        with patch.dict("sys.modules", {"keyring": None}):
            loaded = self.store.load()
        self.assertEqual(loaded["email"], "fallback@example.com")

    def test_keyring_delete_clears_entry(self):
        payload = {"email": "del-kr@example.com"}
        with patch.dict("sys.modules", {"keyring": self.mock_keyring}):
            self.store.save(payload)
            self.store.delete()
            loaded = self.store.load()
        self.assertIsNone(loaded)


# ---------------------------------------------------------------------------
# 7. JWT payload decoding
# ---------------------------------------------------------------------------


class TestDecodeIdTokenPayload(unittest.TestCase):
    def _make_jwt(self, payload: dict) -> str:
        """Construct a fake JWT with a real base64url payload segment."""
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        body = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
            .rstrip(b"=")
            .decode()
        )
        sig = base64.urlsafe_b64encode(b"fakesignature").rstrip(b"=").decode()
        return f"{header}.{body}.{sig}"

    def test_extracts_standard_claims(self):
        from hamster.auth.user import decode_id_token_payload

        claims = {"sub": "12345", "email": "jwt@example.com", "name": "JWT User"}
        jwt = self._make_jwt(claims)
        decoded = decode_id_token_payload(jwt)
        self.assertEqual(decoded["sub"], "12345")
        self.assertEqual(decoded["email"], "jwt@example.com")
        self.assertEqual(decoded["name"], "JWT User")

    def test_raises_on_invalid_jwt_format(self):
        from hamster.auth.user import decode_id_token_payload

        with self.assertRaises(ValueError):
            decode_id_token_payload("not.a.valid.jwt.with.too.many.parts")

    def test_handles_missing_padding_gracefully(self):
        """JWT payloads rarely have padding — decoder must add it."""
        from hamster.auth.user import decode_id_token_payload

        # Construct a payload whose base64 length is not a multiple of 4
        claims = {"sub": "abc", "email": "pad@example.com", "name": "Pad"}
        jwt = self._make_jwt(claims)
        decoded = decode_id_token_payload(jwt)
        self.assertEqual(decoded["email"], "pad@example.com")


# ---------------------------------------------------------------------------
# 8. User profile extraction
# ---------------------------------------------------------------------------


class TestGetProfile(unittest.TestCase):
    def _make_jwt(self, payload: dict) -> str:
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
        body = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
            .rstrip(b"=")
            .decode()
        )
        sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
        return f"{header}.{body}.{sig}"

    def test_profile_extracted_from_id_token(self):
        from hamster.auth.user import get_profile

        claims = {
            "sub": "uid-001",
            "email": "alice@example.com",
            "name": "Alice",
            "picture": "https://img",
        }
        jwt = self._make_jwt(claims)
        profile = get_profile({"id_token": jwt, "access_token": "tok"})
        self.assertEqual(profile.email, "alice@example.com")
        self.assertEqual(profile.name, "Alice")
        self.assertEqual(profile.sub, "uid-001")
        self.assertEqual(profile.picture, "https://img")

    def test_profile_falls_back_to_userinfo_endpoint(self):
        """When id_token is absent, falls back to /userinfo GET."""
        from hamster.auth.user import get_profile

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "sub": "uid-002",
            "email": "bob@example.com",
            "name": "Bob",
            "picture": "https://bob.img",
        }
        # requests is lazily imported inside _fetch_userinfo — patch it there
        with patch("requests.get", return_value=mock_resp):
            profile = get_profile({"access_token": "tok-bob"})

        self.assertEqual(profile.email, "bob@example.com")
        self.assertEqual(profile.name, "Bob")

    def test_raises_when_no_access_token_and_no_id_token(self):
        from hamster.auth.user import get_profile

        with self.assertRaises(RuntimeError):
            get_profile({})

    def test_user_profile_is_complete_check(self):
        from hamster.auth.user import UserProfile

        p = UserProfile(email="e@x.com", name="Test", sub="123")
        self.assertTrue(p.is_complete())
        p2 = UserProfile(email="", name="Test", sub="123")
        self.assertFalse(p2.is_complete())


if __name__ == "__main__":
    unittest.main()
