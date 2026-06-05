from datetime import datetime, timezone
from typing import List, cast

from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
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
    description="""
Register a new user account with email and password.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPass1!"
}
```

**Password requirements:** minimum 8 characters, at least one uppercase letter, one digit.

**On success (201):**
- User is created with `is_active = false`.
- An activation email with a token is sent to the provided address.
- The user must activate the account before logging in.

**Error responses:**
- `409` — A user with this email already exists.
- `422` — Validation error (invalid email format or weak password).
    """,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
        user_data: UserRegistrationRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> UserRegistrationResponseSchema:
    """
    Create a new user account.

    Assigns the user to the default 'USER' group, generates an activation token,
    and sends an activation email. The account remains inactive until confirmed.

    Args:
        user_data: UserRegistrationRequestSchema with email and password.

    Raises:
        409: User with this email already exists.
        500: Default user group not found in database.

    Returns:
        UserRegistrationResponseSchema: id and email of the created user.
    """
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
        await db.flush()
        token_value = activation_token.token

        await db.commit()
        await db.refresh(new_user)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during user creation.",
        ) from e
    else:
        await email_sender.send_activation_email(
            new_user.email,
            "http://localhost:8000/api/v1/accounts/activate/",
            token=token_value,
        )
        return UserRegistrationResponseSchema.model_validate(new_user)


# ─── Activation ──────────────────────────────────────────────────────────────

@router.post(
    "/activate/",
    response_model=MessageResponseSchema,
    summary="Activate User Account",
    description="""
Activate a user account using the token received by email after registration.

**Request body:**
```json
{
  "email": "user@example.com",
  "token": "abc123xyz..."
}
```

The token is sent to the user's email and is valid for **24 hours**.

**On success:** Account is activated and a confirmation email is sent.

**Error responses:**
- `400` — Invalid token, expired token, or token/email mismatch.
- `400` — Account is already active.

After activation, use `POST /api/v1/accounts/login/` to obtain tokens.
    """,
    status_code=status.HTTP_200_OK,
)
async def activate_account(
        activation_data: UserActivationRequestSchema,
        db: AsyncSession = Depends(get_db),
        email_sender: EmailSenderInterface = Depends(get_accounts_email_notificator),
) -> MessageResponseSchema:
    """
    Activate a user account via the email token.

    Looks up the ActivationToken by email+token pair. If found and not expired,
    sets user.is_active = True and deletes the token. Sends a confirmation email.

    Args:
        activation_data: UserActivationRequestSchema with email and token.

    Raises:
        400: Token is invalid, expired, or account is already active.

    Returns:
        MessageResponseSchema: Success message.
    """
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

    new_token = await accounts_service.resend_activation_token(db, cast(int, user.id))
    await email_sender.send_activation_email(
        user.email,
        "http://localhost:8000/api/v1/accounts/activate/",
        token=new_token.token,
    )
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
    description="""
Authenticate a user and return a JWT access token and refresh token.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPass1!"
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

Use the `access_token` as `Bearer <token>` in the `Authorization` header for protected endpoints.
The `refresh_token` is used to get a new access token via `POST /api/v1/accounts/token/refresh/`.

**Error responses:**
- `400` — Invalid credentials or account is not yet activated.
    """,
    status_code=status.HTTP_200_OK,
)
async def login_user(
        data: UserLoginRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
        settings: BaseAppSettings = Depends(get_settings),
) -> UserLoginResponseSchema:
    """
    Authenticate a user and issue JWT tokens.

    Verifies email, active status, and password. Creates and stores a RefreshToken
    in the database. Returns access_token (short-lived) and refresh_token (long-lived).

    Args:
        data: UserLoginRequestSchema with email and password.

    Raises:
        400: Invalid credentials or account is inactive.

    Returns:
        UserLoginResponseSchema: access_token, refresh_token, token_type.
    """
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
    try:
        await db.commit()
    except IntegrityError:
        # Identical token already in DB (two logins within the same second produce the
        # same JWT). The existing token is still valid — just return it.
        await db.rollback()

    return UserLoginResponseSchema(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/logout/",
    response_model=MessageResponseSchema,
    summary="User Logout",
    description="""
Revoke the user's refresh token to log them out.

**Request body:**
```json
{
  "refresh_token": "eyJ..."
}
```

The refresh token is deleted from the database. Subsequent calls to `token/refresh/`
with this token will return `400`.

The access token remains valid until it expires (use short TTL in production).

**No auth header required** — only the refresh token in the request body.
    """,
    status_code=status.HTTP_200_OK,
)
async def logout_user(
        data: TokenRefreshRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> MessageResponseSchema:
    """
    Revoke the provided refresh token to invalidate the user session.

    Deletes the RefreshToken record from the database regardless of token validity.
    Safe to call even with an expired token.

    Args:
        data: TokenRefreshRequestSchema with refresh_token.

    Returns:
        MessageResponseSchema: "Logged out." confirmation message.
    """
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
    description="""
Exchange a valid refresh token for a new access token without re-entering credentials.

**Request body:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

**Error responses:**
- `400` — Refresh token is invalid, expired, or not found in the database (already revoked).
    """,
    status_code=status.HTTP_200_OK,
)
async def refresh_access_token(
        data: TokenRefreshRequestSchema,
        db: AsyncSession = Depends(get_db),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
) -> TokenRefreshResponseSchema:
    """
    Issue a new access token using a valid refresh token.

    Verifies JWT signature, checks token exists in DB (not revoked),
    then creates a new access token for the token owner.

    Args:
        data: TokenRefreshRequestSchema with refresh_token.

    Raises:
        400: Token is invalid, expired, or revoked (not in DB).

    Returns:
        TokenRefreshResponseSchema: New access_token.
    """
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
    description="""
Returns a paginated list of all registered users in the system.

**Query parameters:**
- `page` (int, default: 1) — page number
- `size` (int, default: 20) — items per page

**Response fields per user:**
- `id` — user ID
- `email` — user email
- `is_active` — whether the account is activated
- `group` — role: `USER` | `MODERATOR` | `ADMIN`

**Auth:** Admin role required.
    """,
    status_code=status.HTTP_200_OK,
)
async def list_users(
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
        page: int = 1,
        size: int = 20,
) -> List[UserListItemSchema]:
    """
    Retrieve a paginated list of all users with their roles.

    Args:
        page: Page number (1-based).
        size: Number of users per page.

    Returns:
        list[UserListItemSchema]: id, email, is_active, group for each user.
    """
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
    description="""
Assign a different role (group) to a specific user.

**Path parameter:**
- `user_id` (int) — ID of the user to update.

**Request body:**
```json
{
  "group": "MODERATOR"
}
```

**Available groups:** `USER` | `MODERATOR` | `ADMIN`

**Error responses:**
- `404` — User not found.

**Auth:** Admin role required.
    """,
    status_code=status.HTTP_200_OK,
)
async def change_user_group(
        user_id: int,
        data: ChangeGroupRequestSchema,
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
) -> MessageResponseSchema:
    """
    Update the role (group) of a specific user.

    Args:
        user_id: ID of the user to update.
        data: ChangeGroupRequestSchema with the target group name.

    Raises:
        404: User not found.

    Returns:
        MessageResponseSchema: Confirmation message with the new group.
    """
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
    description="""
Force-activate a user account without requiring the email activation token.

Useful when a user cannot access their email or when the activation email was not received.

**Path parameter:**
- `user_id` (int) — ID of the user to activate.

**Error responses:**
- `404` — User not found.
- `400` — Account is already active.

**Auth:** Admin role required.
    """,
    status_code=status.HTTP_200_OK,
)
async def activate_user_manually(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        _admin: UserModel = Depends(require_admin),
) -> MessageResponseSchema:
    """
    Manually set a user's is_active flag to True without token verification.

    Args:
        user_id: ID of the user to activate.

    Raises:
        404: User not found.
        400: Account is already active.

    Returns:
        MessageResponseSchema: Confirmation of activation.
    """
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
