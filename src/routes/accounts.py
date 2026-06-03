from datetime import datetime, timezone
from typing import List, cast

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from config import get_jwt_auth_manager, get_settings, BaseAppSettings, get_accounts_email_notificator
from database import (
    get_db,
    UserModel,
    UserGroupModel,
    UserGroupEnum,
    ActivationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
)
from exceptions import BaseSecurityError
from notifications import EmailSenderInterface
from schemas import (
    UserRegistrationRequestSchema,
    UserRegistrationResponseSchema,
    MessageResponseSchema,
    UserActivationRequestSchema,
    PasswordResetRequestSchema,
    PasswordResetCompleteRequestSchema,
    UserLoginResponseSchema,
    UserLoginRequestSchema,
    TokenRefreshRequestSchema,
    TokenRefreshResponseSchema,
    ChangePasswordRequestSchema,
    ChangeGroupRequestSchema,
    UserListItemSchema,
)
from security.deps import get_current_user, require_admin
from security.interfaces import JWTAuthManagerInterface
from services import accounts as accounts_service

router = APIRouter()


# ─── Registration ────────────────────────────────────────────────────────────

@router.post(
    "/register/",
    response_model=UserRegistrationResponseSchema,
    summary="User Registration",
    description="Register a new user with an email and password.",
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
        user_data: UserRegistrationRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> UserRegistrationResponseSchema:
    stmt = select(UserModel).where(UserModel.email == user_data.email)
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A user with this email {user_data.email} already exists.",
        )

    stmt = select(UserGroupModel).where(UserGroupModel.name == UserGroupEnum.USER)
    result = await db.execute(stmt)
    user_group = result.scalars().first()
    if not user_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default user group not found.",
        )

    try:
        new_user = UserModel.create(
            email=str(user_data.email),
            raw_password=user_data.password,
            group_id=user_group.id,
        )
        db.add(new_user)
        await db.flush()

        activation_token = ActivationTokenModel(user_id=new_user.id)
        db.add(activation_token)

        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from e
    else:
        await email_sender.send_activation_email(new_user.email, "http://127.0.0.1/accounts/activate/")
        return UserRegistrationResponseSchema.model_validate(new_user)


# ─── Activation ──────────────────────────────────────────────────────────────

@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    description="Activate a user's account using their email and activation token.",
    status_code=status.HTTP_200_OK,
)
async def activate_account(
        activation_data: UserActivationRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    stmt = (
        select(ActivationTokenModel)
        .options(joinedload(ActivationTokenModel.user))
        .join(UserModel)
        .where(
            UserModel.email == activation_data.email,
            ActivationTokenModel.token == activation_data.token,
        )
    )
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    now_utc = datetime.now(timezone.utc)
    if not token_record or cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc) < now_utc:
        if token_record:
            await db.delete(token_record)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired activation token.",
        )

    user = token_record.user
    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    user.is_active = True
    await db.delete(token_record)
    await db.commit()

    await email_sender.send_activation_complete_email(
        str(activation_data.email), "http://127.0.0.1/accounts/login/"
    )
    return MessageResponseSchema(message="User account activated successfully.")


# ─── 1.4 · Resend Activation ─────────────────────────────────────────────────

@router.post(
    "/activation/resend/",
    response_model=MessageResponseSchema,
    summary="Resend Activation Token",
    description=(
        "Request a new activation link if the previous one has expired. "
        "Returns the same generic message regardless of whether the email is registered "
        "to avoid user enumeration."
    ),
    status_code=status.HTTP_200_OK,
)
async def resend_activation(
        data: PasswordResetRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    GENERIC_MSG = "If you are registered and not yet active, you will receive a new activation email."

    stmt = select(UserModel).filter_by(email=str(data.email))
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or user.is_active:
        return MessageResponseSchema(message=GENERIC_MSG)

    await accounts_service.resend_activation_token(db, cast(int, user.id))
    await email_sender.send_activation_email(user.email, "http://127.0.0.1/accounts/activate/")
    return MessageResponseSchema(message=GENERIC_MSG)


# ─── Password Reset ───────────────────────────────────────────────────────────

@router.post(
    "/password-reset/request/",
    response_model=MessageResponseSchema,
    summary="Request Password Reset Token",
    description=(
        "Allows a user to request a password reset token. If the user exists and is active, "
        "a new token will be generated and any existing tokens will be invalidated."
    ),
    status_code=status.HTTP_200_OK,
)
async def request_password_reset_token(
        data: PasswordResetRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active:
        return MessageResponseSchema(message="If you are registered, you will receive an email with instructions.")

    await db.execute(delete(PasswordResetTokenModel).where(PasswordResetTokenModel.user_id == user.id))
    reset_token = PasswordResetTokenModel(user_id=cast(int, user.id))
    db.add(reset_token)
    await db.commit()

    await email_sender.send_password_reset_email(
        str(data.email), "http://127.0.0.1/accounts/password-reset-complete/"
    )
    return MessageResponseSchema(message="If you are registered, you will receive an email with instructions.")


@router.post(
    "/reset-password/complete/",
    response_model=MessageResponseSchema,
    summary="Reset User Password",
    description="Reset a user's password if a valid token is provided.",
    status_code=status.HTTP_200_OK,
)
async def reset_password(
        data: PasswordResetCompleteRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token.")

    stmt = select(PasswordResetTokenModel).filter_by(user_id=user.id)
    result = await db.execute(stmt)
    token_record = result.scalars().first()

    if not token_record or token_record.token != data.token:
        if token_record:
            await db.delete(token_record)
            await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token.")

    expires_at = cast(datetime, token_record.expires_at).replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.delete(token_record)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email or token.")

    try:
        user.password = data.password
        await db.delete(token_record)
        await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting the password.",
        ) from e

    await email_sender.send_password_reset_complete_email(
        str(data.email), "http://127.0.0.1/accounts/login/"
    )
    return MessageResponseSchema(message="Password has been reset successfully.")


# ─── 1.1 · Change Password (authenticated) ───────────────────────────────────

@router.post(
    "/change-password/",
    response_model=MessageResponseSchema,
    summary="Change Password",
    description="Change the current user's password. Requires the old password for verification.",
    status_code=status.HTTP_200_OK,
)
async def change_password(
        data: ChangePasswordRequestSchema,
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user),
) -> MessageResponseSchema:
    if not current_user.verify_password(data.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    try:
        current_user.password = data.new_password
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()
    return MessageResponseSchema(message="Password changed successfully.")


# ─── Login / Logout / Token Refresh ──────────────────────────────────────────

@router.post(
    "/login/",
    response_model=UserLoginResponseSchema,
    summary="User Login",
    description="Authenticate user and return access and refresh tokens.",
    status_code=status.HTTP_200_OK,
)
async def login_user(
        data: UserLoginRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
        settings: BaseAppSettings = Depends(get_settings),
) -> UserLoginResponseSchema:
    stmt = select(UserModel).filter_by(email=data.email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not user.is_active or not user.verify_password(data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid credentials or inactive account.",
        )

    access_token = jwt_manager.create_access_token({"user_id": user.id})
    refresh_token = jwt_manager.create_refresh_token({"user_id": user.id})

    rt = RefreshTokenModel.create(user_id=user.id, days_valid=settings.LOGIN_TIME_DAYS, token=refresh_token)
    db.add(rt)
    await db.commit()

    return UserLoginResponseSchema(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="User Logout",
    description="Log out user by revoking their refresh token.",
    status_code=status.HTTP_200_OK,
)
async def logout_user(
        data: TokenRefreshRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> MessageResponseSchema:
    try:
        jwt_manager.verify_refresh_token_or_raise(data.refresh_token)
    except BaseSecurityError:
        pass

    await db.execute(delete(RefreshTokenModel).where(RefreshTokenModel.token == data.refresh_token))
    await db.commit()
    return MessageResponseSchema(message="Logged out.")


@router.post(
    "/token/refresh/",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh Access Token",
    description="Exchange a valid refresh token for a new access token.",
    status_code=status.HTTP_200_OK,
)
async def refresh_access_token(
        data: TokenRefreshRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    try:
        jwt_manager.decode_refresh_token(data.refresh_token)
    except BaseSecurityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired refresh token.",
        )

    stmt = select(RefreshTokenModel).filter_by(token=data.refresh_token)
    result = await db.execute(stmt)
    token_record = result.scalars().first()
    if not token_record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid refresh token.")

    access_token = jwt_manager.create_access_token({"user_id": token_record.user_id})
    return TokenRefreshResponseSchema(access_token=access_token)


# ─── 1.2 · Admin Endpoints ───────────────────────────────────────────────────

@router.get(
    "/users/",
    response_model=List[UserListItemSchema],
    summary="List All Users",
    description="Returns a paginated list of all registered users. Accessible by Admins and Moderators.",
    status_code=status.HTTP_200_OK,
)
async def list_users(
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
        page: int = 1,
        size: int = 20,
) -> List[UserListItemSchema]:
    offset = (page - 1) * size
    stmt = (
        select(UserModel)
        .options(selectinload(UserModel.group))
        .order_by(UserModel.id)
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [
        UserListItemSchema(
            id=u.id,
            email=u.email,
            is_active=u.is_active,
            group=u.group.name.value,
        )
        for u in users
    ]


@router.patch(
    "/users/{user_id}/group/",
    response_model=MessageResponseSchema,
    summary="Change User Group",
    description="Assign a different group (role) to a user. Admin only.",
    status_code=status.HTTP_200_OK,
)
async def change_user_group(
        user_id: int,
        data: ChangeGroupRequestSchema,
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
) -> MessageResponseSchema:
    stmt = select(UserModel).options(selectinload(UserModel.group)).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    stmt = select(UserGroupModel).where(UserGroupModel.name == data.group)
    result = await db.execute(stmt)
    new_group = result.scalars().first()
    if not new_group:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Group '{data.group}' not found in the database.",
        )

    user.group_id = new_group.id
    await db.commit()
    return MessageResponseSchema(message=f"User {user_id} group updated to '{data.group.value}'.")


@router.patch(
    "/users/{user_id}/activate/",
    response_model=MessageResponseSchema,
    summary="Manually Activate User",
    description="Manually activate a user account without requiring an activation token. Admin only.",
    status_code=status.HTTP_200_OK,
)
async def activate_user_manually(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
) -> MessageResponseSchema:
    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is already active.",
        )

    user.is_active = True
    await db.execute(delete(ActivationTokenModel).where(ActivationTokenModel.user_id == user_id))
    await db.commit()
    return MessageResponseSchema(message=f"User {user_id} has been activated.")
