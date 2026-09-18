import base64
import hashlib

from backend.app.auth.session_tokens import (
    hash_token,
    issue_session_secrets,
    verify_token,
)


def _decode_token(token: str) -> bytes:
    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + padding)


def test_issue_session_secrets_uses_independent_256_bit_tokens() -> None:
    issued = issue_session_secrets()

    assert issued.session_id.version == 4
    assert len(_decode_token(issued.session_token)) == 32
    assert len(_decode_token(issued.csrf_token)) == 32
    assert issued.session_token != issued.csrf_token


def test_issue_session_secrets_never_reuses_tokens() -> None:
    first = issue_session_secrets()
    second = issue_session_secrets()

    assert first.session_id != second.session_id
    assert first.session_token != second.session_token
    assert first.csrf_token != second.csrf_token


def test_token_hashes_are_binary_sha256_digests() -> None:
    issued = issue_session_secrets()

    assert issued.session_token_hash == hashlib.sha256(
        issued.session_token.encode("utf-8")
    ).digest()
    assert issued.csrf_token_hash == hash_token(issued.csrf_token)
    assert len(issued.session_token_hash) == 32
    assert len(issued.csrf_token_hash) == 32


def test_verify_token_accepts_only_matching_token() -> None:
    issued = issue_session_secrets()

    assert verify_token(issued.session_token, issued.session_token_hash) is True
    assert verify_token("different-token", issued.session_token_hash) is False


def test_session_secret_representations_are_redacted() -> None:
    issued = issue_session_secrets()
    representation = repr(issued)

    assert issued.session_token not in representation
    assert issued.csrf_token not in representation
    assert "redacted" in representation.lower()
