"""Read (unverified) claims out of a JWT, to decide when to refresh.

These helpers decode the payload segment only and never verify the signature —
penpine reads the expiry to schedule a refresh, it does not trust the token.
"""

from __future__ import annotations

import base64
import json


def jwt_claims(token: str) -> dict:
    """Decode a JWT's payload claims. Returns ``{}`` when the token is not a
    parseable JWT (wrong shape, bad base64, non-object payload)."""
    try:
        payload_b64 = token.split(".")[1]  # header.payload.signature
        payload_b64 += "=" * (-len(payload_b64) % 4)  # restore base64url padding
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def jwt_expiry(token: str) -> float | None:
    """The ``exp`` claim as an absolute unix timestamp, or ``None`` if absent.

    ``exp`` is already absolute, so it maps straight onto ``Session.expires_at``
    (no ``time.time()`` offset, unlike an ``expires_in`` duration)."""
    exp = jwt_claims(token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None
