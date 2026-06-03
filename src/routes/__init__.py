from fastapi import APIRouter
from .accounts import router as accounts_router

profiles_router = APIRouter()
movie_router = APIRouter()

__all__ = ["accounts_router", "profiles_router", "movie_router"]
