"""
Tests for Celery-beat cleanup tasks:
  - Expired ActivationToken cleanup
  - Expired PasswordResetToken cleanup
  - Expired RefreshToken cleanup
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from database import (
    get_db,
    UserModel,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
)
from tasks.cleanup import (
    cleanup_expired_activation_tokens,
    cleanup_expired_password_reset_tokens,
    cleanup_expired_refresh_tokens,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _past(hours=1):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _future(hours=24):
    return datetime.now(timezone.utc) + timedelta(hours=hours)


async def _make_user(db, email, group_id=1):
    user = UserModel.create(email=email, raw_password='Strong1!Pass', group_id=group_id)
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# ActivationToken cleanup
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cleanup_expired_activation_tokens():
    async for db in get_db():
        u1 = await _make_user(db, 'act_exp@test.com')
        u2 = await _make_user(db, 'act_valid@test.com')
        expired = ActivationTokenModel(user_id=u1.id, expires_at=_past())
        valid = ActivationTokenModel(user_id=u2.id, expires_at=_future())
        db.add_all([expired, valid])
        await db.commit()

        deleted = await cleanup_expired_activation_tokens(db)
        assert deleted == 1

        async for db2 in get_db():
            result = await db2.execute(
                select(ActivationTokenModel).where(ActivationTokenModel.user_id == u1.id)
            )
            assert result.scalars().first() is None
            result2 = await db2.execute(
                select(ActivationTokenModel).where(ActivationTokenModel.user_id == u2.id)
            )
            assert result2.scalars().first() is not None
            break
        break


@pytest.mark.anyio
async def test_cleanup_activation_tokens_when_none_expired():
    async for db in get_db():
        u = await _make_user(db, 'act_noop@test.com')
        db.add(ActivationTokenModel(user_id=u.id, expires_at=_future()))
        await db.commit()
        deleted = await cleanup_expired_activation_tokens(db)
        assert deleted == 0
        break


# ---------------------------------------------------------------------------
# PasswordResetToken cleanup
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cleanup_expired_password_reset_tokens():
    async for db in get_db():
        u1 = await _make_user(db, 'pw_exp@test.com')
        u2 = await _make_user(db, 'pw_valid@test.com')
        expired = PasswordResetTokenModel(user_id=u1.id, expires_at=_past())
        valid = PasswordResetTokenModel(user_id=u2.id, expires_at=_future())
        db.add_all([expired, valid])
        await db.commit()

        deleted = await cleanup_expired_password_reset_tokens(db)
        assert deleted == 1

        async for db2 in get_db():
            res = await db2.execute(
                select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == u1.id)
            )
            assert res.scalars().first() is None
            res2 = await db2.execute(
                select(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == u2.id)
            )
            assert res2.scalars().first() is not None
            break
        break


@pytest.mark.anyio
async def test_cleanup_password_reset_tokens_when_none_expired():
    async for db in get_db():
        u = await _make_user(db, 'pw_noop@test.com')
        db.add(PasswordResetTokenModel(user_id=u.id, expires_at=_future()))
        await db.commit()
        deleted = await cleanup_expired_password_reset_tokens(db)
        assert deleted == 0
        break


# ---------------------------------------------------------------------------
# RefreshToken cleanup
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cleanup_expired_refresh_tokens():
    async for db in get_db():
        u1 = await _make_user(db, 'ref_exp@test.com')
        u2 = await _make_user(db, 'ref_valid@test.com')
        u1.is_active = True
        u2.is_active = True
        await db.flush()

        expired = RefreshTokenModel(user_id=u1.id, expires_at=_past(hours=2))
        valid = RefreshTokenModel(user_id=u2.id, expires_at=_future(hours=72))
        db.add_all([expired, valid])
        await db.commit()

        deleted = await cleanup_expired_refresh_tokens(db)
        assert deleted == 1

        async for db2 in get_db():
            res = await db2.execute(
                select(RefreshTokenModel).where(RefreshTokenModel.user_id == u1.id)
            )
            assert res.scalars().first() is None
            res2 = await db2.execute(
                select(RefreshTokenModel).where(RefreshTokenModel.user_id == u2.id)
            )
            assert res2.scalars().first() is not None
            break
        break


@pytest.mark.anyio
async def test_cleanup_refresh_tokens_multiple_expired():
    async for db in get_db():
        u = await _make_user(db, 'ref_multi@test.com')
        u.is_active = True
        await db.flush()
        for i in range(3):
            db.add(RefreshTokenModel(user_id=u.id, expires_at=_past(hours=i + 1)))
        db.add(RefreshTokenModel(user_id=u.id, expires_at=_future()))
        await db.commit()

        deleted = await cleanup_expired_refresh_tokens(db)
        assert deleted == 3
        break
