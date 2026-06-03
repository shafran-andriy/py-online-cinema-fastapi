from fastapi import APIRouter
from .accounts import router as accounts_router
from .movies import router as movie_router

profiles_router = APIRouter()

__all__ = ["accounts_router", "profiles_router", "movie_router"]
