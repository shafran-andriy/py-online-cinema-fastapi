import uuid as uuid_lib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_s3_storage_client
from database import get_db, UserModel, UserProfileModel
from schemas import UserProfileResponseSchema, UserProfileUpdateSchema
from security.deps import get_current_user
from storages import S3StorageInterface

router = APIRouter()

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


async def _get_or_create_profile(db: AsyncSession, user_id: int) -> UserProfileModel:
    stmt = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
    result = await db.execute(stmt)
    profile = result.scalars().first()
    if not profile:
        profile = UserProfileModel(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


# ─── GET /me/ ─────────────────────────────────────────────────────────────────

@router.get(
    "/me/",
    response_model=UserProfileResponseSchema,
    summary="Get My Profile",
    description=(
        "Returns the profile of the currently authenticated user. "
        "An empty profile is created automatically on first access."
    ),
    status_code=status.HTTP_200_OK,
)
async def get_my_profile(
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user),
) -> UserProfileResponseSchema:
    profile = await _get_or_create_profile(db, current_user.id)
    return UserProfileResponseSchema.model_validate(profile)


# ─── PATCH /me/ ───────────────────────────────────────────────────────────────

@router.patch(
    "/me/",
    response_model=UserProfileResponseSchema,
    summary="Update My Profile",
    description="Update one or more fields of the current user's profile. Only provided fields are changed.",
    status_code=status.HTTP_200_OK,
)
async def update_my_profile(
        data: UserProfileUpdateSchema,
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user),
) -> UserProfileResponseSchema:
    profile = await _get_or_create_profile(db, current_user.id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return UserProfileResponseSchema.model_validate(profile)


# ─── POST /me/avatar/ ─────────────────────────────────────────────────────────

@router.post(
    "/me/avatar/",
    response_model=UserProfileResponseSchema,
    summary="Upload Avatar",
    description=(
        "Upload a profile avatar image (JPEG, PNG, GIF, or WebP). "
        "The file is stored in S3-compatible storage (MinIO) and the profile avatar URL is updated."
    ),
    status_code=status.HTTP_200_OK,
)
async def upload_my_avatar(
        file: UploadFile = File(..., description="Avatar image file"),
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user),
        s3: S3StorageInterface = Depends(get_s3_storage_client),
) -> UserProfileResponseSchema:
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{file.content_type}'. Allowed: {', '.join(sorted(_ALLOWED_IMAGE_TYPES))}",
        )

    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else "jpg"
    key = f"avatars/{current_user.id}/{uuid_lib.uuid4()}.{ext}"

    raw = await file.read()
    avatar_url = await s3.upload_fileobj(raw, key, content_type=file.content_type or "application/octet-stream")

    profile = await _get_or_create_profile(db, current_user.id)
    profile.avatar = avatar_url
    await db.commit()
    await db.refresh(profile)
    return UserProfileResponseSchema.model_validate(profile)
