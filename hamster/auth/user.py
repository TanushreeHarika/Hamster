"""hamster.auth.user — User profile extraction from Google OAuth tokens.

Decodes the JWT ``id_token`` payload (no signature verification — only the
middle Base64URL segment is needed for profile display) and falls back to
a live ``GET /userinfo`` call when claims are missing.

Usage::

    token_data = {"id_token": "...", "access_token": "..."}
    profile = get_profile(token_data)
    print(profile.email, profile.name)
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any


GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class UserProfile:
    """Structured representation of a Google user's public profile.

    Attributes:
        email:   Primary email address (e.g. ``"alice@gmail.com"``).
        name:    Full display name (e.g. ``"Alice Smith"``).
        picture: URL of the profile picture (may be empty).
        sub:     Unique Google account identifier (stable across sessions).
        raw:     Original claims dict for forward-compatibility.
    """
    email:   str               = ""
    name:    str               = ""
    picture: str               = ""
    sub:     str               = ""
    raw:     dict[str, Any]    = field(default_factory=dict, repr=False)

    def is_complete(self) -> bool:
        """Return ``True`` if all required display fields are populated."""
        return bool(self.email and self.name and self.sub)


# ---------------------------------------------------------------------------
# JWT payload decoder
# ---------------------------------------------------------------------------

def decode_id_token_payload(id_token: str) -> dict[str, Any]:
    """Decode the payload segment of a JWT without verifying its signature.

    The Google ``id_token`` is a standard JWT (three base64url segments separated
    by ``.``).  The middle segment contains the user claims.  We add padding
    ourselves because ``base64.urlsafe_b64decode`` requires it.

    Args:
        id_token: Raw JWT string from the token endpoint response.

    Returns:
        Decoded claims dict (e.g. ``{"sub": "...", "email": "...", "name": "..."}``)

    Raises:
        ValueError: If *id_token* does not look like a valid JWT.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"id_token does not look like a JWT: expected 3 segments, "
            f"got {len(parts)}"
        )
    payload_b64 = parts[1]
    # Add padding so that base64 decodes correctly (length must be multiple of 4)
    padding = 4 - (len(payload_b64) % 4)
    if padding != 4:
        payload_b64 += "=" * padding
    raw_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(raw_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def _profile_from_claims(claims: dict[str, Any]) -> UserProfile:
    """Build a ``UserProfile`` from a Google claims dict."""
    return UserProfile(
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
        sub=claims.get("sub", ""),
        raw=claims,
    )


def _fetch_userinfo(access_token: str) -> dict[str, Any]:
    """GET Google's ``/userinfo`` endpoint to retrieve profile claims.

    Uses ``requests`` (already a project dependency) so we get connection
    pooling and timeout handling for free.

    Args:
        access_token: Valid OAuth 2.0 access token.

    Returns:
        Parsed userinfo response dict.

    Raises:
        RuntimeError: If the HTTP call fails or returns a non-2xx status.
    """
    try:
        import requests  # already in project dependencies
    except ImportError as exc:
        raise RuntimeError(
            "The `requests` package is required for the userinfo fallback. "
            "Run `uv pip install -e .` to install project dependencies."
        ) from exc

    resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Google userinfo endpoint returned {resp.status_code}: {resp.text}"
        )
    return resp.json()


def get_profile(token_data: dict[str, Any]) -> UserProfile:
    """Extract a complete ``UserProfile`` from an OAuth token response.

    Strategy:
    1. Try to decode ``id_token`` JWT payload (fast, no network call).
    2. If the profile is incomplete or ``id_token`` is absent, fall back to a
       live GET request to Google's ``/userinfo`` endpoint using ``access_token``.

    Args:
        token_data: Dict returned by :func:`hamster.auth.oauth.exchange_code`
                    or loaded from :class:`hamster.auth.store.SecureTokenStore`.

    Returns:
        Populated ``UserProfile`` instance.

    Raises:
        RuntimeError: If neither the JWT nor the userinfo endpoint provides
                      sufficient data.
    """
    id_token = token_data.get("id_token", "")
    if id_token:
        try:
            claims = decode_id_token_payload(id_token)
            profile = _profile_from_claims(claims)
            if profile.is_complete():
                return profile
        except (ValueError, json.JSONDecodeError):
            pass  # Fall through to userinfo endpoint

    # Fallback: live userinfo request
    access_token = token_data.get("access_token", "")
    if not access_token:
        raise RuntimeError(
            "No access_token available — cannot fetch user profile. "
            "Please run `hamster login` again."
        )

    claims = _fetch_userinfo(access_token)
    profile = _profile_from_claims(claims)
    if not profile.email:
        raise RuntimeError(
            "Could not retrieve user email from Google. "
            "Ensure the 'email' scope was granted."
        )
    return profile
