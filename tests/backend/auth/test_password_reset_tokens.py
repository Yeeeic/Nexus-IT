from uuid import UUID

import pytest

from backend.app.auth.password_reset import (
    PasswordResetToken,
    hash_reset_secret,
    parse_reset_token,
)


PEPPER = b"p" * 32


def test_password_reset_token_has_public_id_and_256_bit_secret() -> None:
    token = PasswordResetToken.generate(PEPPER)

    parsed_id, secret = parse_reset_token(token.value)

    assert parsed_id == token.token_id
    assert len(secret) >= 43
    assert len(token.secret_hash) == 32
    assert token.secret_hash == hash_reset_secret(secret, PEPPER)
    assert secret not in repr(token)
    assert token.value not in repr(token)


@pytest.mark.parametrize(
    "value",
    ["", "missing-separator", "not-a-uuid.secret", f"{UUID(int=0)}."],
)
def test_password_reset_token_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError, match="invalid password reset token"):
        parse_reset_token(value)


def test_password_reset_hash_requires_strong_pepper() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        hash_reset_secret("secret", b"short")
