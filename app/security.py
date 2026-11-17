"""Password hashing, password policy and token helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2id with argon2-cffi's RFC 9106 low-memory defaults; a random 16-byte salt is
# generated per hash and encoded in the output string. Tune cost on the real host.
_hasher = PasswordHasher()
MAX_PASSWORD_LENGTH = 256  # bound hashing work for oversized input

# Verified against when the username is unknown, so response time does not reveal
# whether an account exists.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> tuple[bool, bool]:
    """Return (ok, needs_rehash). Never raises on a bad hash or wrong password."""
    password = password[:MAX_PASSWORD_LENGTH + 1]
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    if stored_hash is None:
        return False, False
    return True, _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, username: str, min_length: int) -> list[str]:
    problems = []
    if len(password) < min_length:
        problems.append(f"Use at least {min_length} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    if username and username.lower() in password.lower():
        problems.append("The password must not contain the username.")
    if password and len(set(password)) < 5:
        problems.append("Use a less repetitive password.")
    return problems


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def temporary_password(min_length: int) -> str:
    return secrets.token_urlsafe(max(16, min_length + 4))
