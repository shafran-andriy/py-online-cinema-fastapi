from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from database import ActivationTokenModel, PasswordResetTokenModel, RefreshTokenModel


async def cleanup_expired_activation_tokens(db: AsyncSession) -> int:
    stmt = delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < datetime.now(timezone.utc))
    result = await db.execute(stmt)
    await db.commit()
    return getattr(result, 'rowcount', 0)


async def cleanup_expired_password_reset_tokens(db: AsyncSession) -> int:
    stmt = delete(PasswordResetTokenModel).where(
        PasswordResetTokenModel.expires_at < datetime.now(timezone.utc)
    )
    result = await db.execute(stmt)
    await db.commit()
    return getattr(result, 'rowcount', 0)


async def cleanup_expired_refresh_tokens(db: AsyncSession) -> int:
    stmt = delete(RefreshTokenModel).where(RefreshTokenModel.expires_at < datetime.now(timezone.utc))
    result = await db.execute(stmt)
    await db.commit()
    return getattr(result, 'rowcount', 0)
