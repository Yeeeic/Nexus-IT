from backend.app.auth.passwords import hash_password, verify_password


def test_hash_password_uses_required_argon2id_parameters() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert "correct horse battery staple" not in password_hash


def test_verify_password_accepts_matching_password() -> None:
    password_hash = hash_password("a sufficiently long password")

    assert verify_password("a sufficiently long password", password_hash) is True


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password("a sufficiently long password")

    assert verify_password("a different password", password_hash) is False


def test_verify_password_rejects_malformed_hash_without_leaking_library_error() -> None:
    assert verify_password("a sufficiently long password", "not-a-password-hash") is False
