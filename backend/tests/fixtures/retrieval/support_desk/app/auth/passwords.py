"""Password hashing and verification."""

import hashlib
import hmac
import os

ITERATIONS = 200_000
SALT_BYTES = 16


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """Derive a salted PBKDF2 hash that can be stored in the users table."""
    salt = salt or os.urandom(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time comparison of a candidate password against a stored hash."""
    _, iterations, salt_hex, digest_hex = stored.split("$")
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(derived.hex(), digest_hex)


def needs_rehash(stored: str) -> bool:
    return int(stored.split("$")[1]) < ITERATIONS
