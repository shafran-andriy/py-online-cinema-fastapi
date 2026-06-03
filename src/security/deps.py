from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config.dependencies import get_jwt_auth_manager, get_settings
from security.interfaces import JWTAuthManagerInterface
from database import get_db, UserModel

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
    db: AsyncSession = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = jwt_manager.decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    stmt = await db.execute(
        "SELECT * FROM users WHERE id = :id",
        {"id": user_id}
    )
    # Use ORM query to fetch
    result = await db.execute("SELECT id FROM users WHERE id=:id", {"id": user_id})
    user = await db.get(UserModel, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def require_moderator(user=Depends(get_current_user)):
    if user.group.name not in ("moderator", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator privileges required")
    return user
