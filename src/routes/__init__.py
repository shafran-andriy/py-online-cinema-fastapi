from .accounts import router as accounts_router
from .movies import router as movie_router
from .profiles import router as profiles_router

__all__ = ["accounts_router", "profiles_router", "movie_router"]
