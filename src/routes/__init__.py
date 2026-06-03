from .accounts import router as accounts_router
from .movies import router as movie_router
from .notifications import router as notifications_router
from .cart import router as cart_router
from .admin import router as admin_router

from fastapi import APIRouter
profiles_router = APIRouter()

__all__ = [
    "accounts_router",
    "profiles_router",
    "movie_router",
    "notifications_router",
    "cart_router",
    "admin_router",
]
