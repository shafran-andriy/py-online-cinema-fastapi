from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from database import (
    UserModel,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel
)
from security.token_manager import JWTAuthManager
from security.utils import generate_secure_token


async def create_user_instance(email: str, raw_password: str, group_id: int) -> UserModel:
    """Create a UserModel instance without committing to DB (helper for services/tests)."""
    return UserModel.create(email=email, raw_password=raw_password, group_id=group_id)


async def create_activation_token_for_user(user: UserModel) -> ActivationTokenModel:
    """Create an ActivationTokenModel instance for given user."""
    return ActivationTokenModel(user_id=user.id if hasattr(user, 'id') else None)


def is_token_expired(token_model) -> bool:
    """Return True if token_model.expires_at is in the past (UTC-aware)."""
    if token_model is None or not hasattr(token_model, 'expires_at'):
        return True
    expires: datetime = token_model.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


async def resend_activation_token(db: AsyncSession, user_id: int) -> ActivationTokenModel:
    """Invalidate old activation token(s) for user and create a new one in DB."""
    await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user_id))
    new_token = ActivationTokenModel(user_id=user_id)
    db.add(new_token)
    await db.commit()
    await db.refresh(new_token)
    return new_token


async def request_password_reset(db: AsyncSession, user_id: int) -> PasswordResetTokenModel:
    """Invalidate previous reset tokens and create a new PasswordResetTokenModel in DB."""
    await db.execute(delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user_id))
    token = PasswordResetTokenModel(user_id=user_id)
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


async def create_refresh_token(db: AsyncSession, user_id: int, days_valid: int, token_str: Optional[str] = None) -> RefreshTokenModel:
    """Create a refresh token record and return it."""
    token_value = token_str or generate_secure_token(64)
    rt = RefreshTokenModel.create(user_id=user_id, days_valid=days_valid, token=token_value)
    db.add(rt)
    await db.commit()
    await db.refresh(rt)
    return rt


async def delete_expired_activation_tokens(db: AsyncSession) -> int:
    """Delete activation tokens that have expired. Returns number deleted."""
    stmt = delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < datetime.now(timezone.utc))
    result = await db.execute(stmt)
    await db.commit()
    # SQLAlchemy's AsyncResult doesn't expose rowcount consistently for all backends; return 0 if not available
    return getattr(result, 'rowcount', 0)
