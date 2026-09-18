"""Ed25519 action signing without exposing private key material."""

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class Ed25519ActionSigner:
    def __init__(self, private_key: bytes, *, key_version: int) -> None:
        if len(private_key) != 32:
            raise ValueError("Ed25519 private key must contain exactly 32 bytes")
        if key_version < 1:
            raise ValueError("key version must be positive")
        self._private_key = Ed25519PrivateKey.from_private_bytes(private_key)
        self.key_version = key_version

    @classmethod
    def from_base64(cls, encoded_key: str, *, key_version: int) -> "Ed25519ActionSigner":
        private_key = base64.b64decode(encoded_key, validate=True)
        return cls(private_key, key_version=key_version)

    def sign(self, payload: bytes) -> str:
        signature = self._private_key.sign(payload)
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
