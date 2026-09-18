import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.app.support.crypto import Ed25519ActionSigner


def test_signer_produces_verifiable_ed25519_signature() -> None:
    raw_key = bytes(range(32))
    signer = Ed25519ActionSigner(raw_key, key_version=3)
    payload = b"nexus-action:v1\nexample"

    encoded_signature = signer.sign(payload)
    signature = base64.urlsafe_b64decode(encoded_signature + "==")

    Ed25519PrivateKey.from_private_bytes(raw_key).public_key().verify(
        signature,
        payload,
    )
    assert signer.key_version == 3
