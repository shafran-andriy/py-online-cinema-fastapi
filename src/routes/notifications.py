from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, NotificationModel, UserModel
from schemas.movies import NotificationSchema
from security.deps import get_current_user

router = APIRouter()


@router.get("/", response_model=List[NotificationSchema], status_code=status.HTTP_200_OK)
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    stmt = (
        select(NotificationModel)
        .where(NotificationModel.user_id == current_user.id)
        .order_by(NotificationModel.created_at.desc())
    )
    result = await db.execute(stmt)
    return [NotificationSchema.model_validate(n) for n in result.scalars().all()]


@router.patch("/{notification_id}/read/", response_model=NotificationSchema, status_code=status.HTTP_200_OK)
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    notif = await db.get(NotificationModel, notification_id)
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notif.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your notification")
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return NotificationSchema.model_validate(notif)
