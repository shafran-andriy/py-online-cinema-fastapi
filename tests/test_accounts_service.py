import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from database.models.accounts import ActivationTokenModel
from services.accounts import is_token_expired, create_activation_token_for_user


def test_is_token_expired_with_none():
    assert is_token_expired(None) is True


def test_is_token_expired_future():
    class T:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    assert is_token_expired(T()) is False


def test_is_token_expired_past():
    class T:
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

    assert is_token_expired(T()) is True


@pytest.mark.asyncio
async def test_create_activation_token_for_user():
    # Creating activation token instance without DB commit should not raise
    class U:
        id = 123

    token = await create_activation_token_for_user(U())
    assert isinstance(token, ActivationTokenModel)
    assert token.user_id == 123
    assert token.token is not None
    assert token.expires_at > datetime.now(timezone.utc)
