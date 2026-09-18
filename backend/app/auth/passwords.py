"""Password hashing and verification using the required Argon2id profile."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a salted Argon2id hash for a validated plaintext password."""
    return _password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a password without exposing parser errors for invalid stored hashes."""
    try:
        return _password_hash.verify(password, encoded_hash)
    except (UnknownHashError, ValueError):
        return False
