from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from database import ActivationTokenModel


async def cleanup_expired_activation_tokens(db: AsyncSession) -> int:
    """Task callable for celery-beat to delete expired activation tokens."""
    stmt = delete(ActivationTokenModel).where(ActivationTokenModel.expires_at < datetime.now(timezone.utc))
    result = await db.execute(stmt)
    await db.commit()
    return getattr(result, 'rowcount', 0)
