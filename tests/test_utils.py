"""
Unit tests for shared utility helpers.
"""
import re
from datetime import datetime, timezone, timedelta

import pytest

from security.passwords import hash_password, verify_password
from security.utils import generate_secure_token
from services.accounts import is_token_expired


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def test_hash_password_is_not_plaintext():
    raw = "MyS3cret!Pass"
    hashed = hash_password(raw)
    assert hashed != raw
    assert len(hashed) > 20


def test_verify_password_correct():
    raw = "CorrectHorseBatteryStaple1!"
    assert verify_password(raw, hash_password(raw))


def test_verify_password_wrong():
    assert not verify_password("WrongPass1!", hash_password("RightPass1!"))


def test_hash_different_each_time():
    raw = "SamePassword1!"
    h1 = hash_password(raw)
    h2 = hash_password(raw)
    assert h1 != h2


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def test_generate_secure_token_returns_string():
    token = generate_secure_token()
    assert isinstance(token, str)
    assert len(token) > 0


def test_generate_secure_token_uniqueness():
    tokens = {generate_secure_token() for _ in range(100)}
    assert len(tokens) == 100


def test_generate_secure_token_urlsafe_chars():
    token = generate_secure_token(32)
    assert re.match(r'^[A-Za-z0-9_\-]+$', token)


def test_generate_secure_token_custom_length():
    short = generate_secure_token(8)
    long = generate_secure_token(64)
    assert len(short) < len(long)


# ---------------------------------------------------------------------------
# Token expiry helper
# ---------------------------------------------------------------------------

class _FakeToken:
    def __init__(self, expires_at):
        self.expires_at = expires_at


def test_is_token_expired_with_past_time():
    token = _FakeToken(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert is_token_expired(token)


def test_is_token_expired_with_future_time():
    token = _FakeToken(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert not is_token_expired(token)


def test_is_token_expired_with_none():
    assert is_token_expired(None)


def test_is_token_expired_naive_datetime():
    token = _FakeToken(expires_at=datetime.utcnow() - timedelta(seconds=1))
    assert is_token_expired(token)
