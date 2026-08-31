"""hamster.auth — Google OAuth 2.0 PKCE authentication package.

Public surface
--------------
from hamster.auth.oauth  import AuthFlow, PKCEParams, generate_pkce_params, generate_state
from hamster.auth.server import SingleRequestHTTPServer, REDIRECT_URI
from hamster.auth.store  import SecureTokenStore
from hamster.auth.user   import get_profile, decode_id_token_payload, UserProfile
"""

from __future__ import annotations

__all__ = [
    "REDIRECT_URI",
    "AuthFlow",
    "PKCEParams",
    "SecureTokenStore",
    "SingleRequestHTTPServer",
    "UserProfile",
    "decode_id_token_payload",
    "generate_pkce_params",
    "generate_state",
    "get_profile",
]
