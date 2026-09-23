"""Signed access tokens (JSON Web Tokens) for API sessions."""

import base64
import hashlib
import hmac
import json
import time

ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 3600


class TokenError(Exception):
    """Raised when a token is expired or its signature does not match."""


def create_access_token(subject: str, secret: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Issue a signed bearer token for a user."""
    payload = {"sub": subject, "exp": int(time.time()) + ttl_seconds}
    header = _encode({"alg": ALGORITHM, "typ": "JWT"})
    body = _encode(payload)
    return f"{header}.{body}.{_sign(f'{header}.{body}', secret)}"


def decode_token(token: str, secret: str) -> dict:
    """Validate the signature and expiry of a bearer token and return its claims."""
    header, body, signature = token.split(".")
    if not hmac.compare_digest(signature, _sign(f"{header}.{body}", secret)):
        raise TokenError("signature mismatch")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    if claims["exp"] < time.time():
        raise TokenError("token expired")
    return claims


def _sign(message: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
