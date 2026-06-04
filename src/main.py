from fastapi import FastAPI

from routes import (
    movie_router,
    accounts_router,
    profiles_router,
)
from routes.docs import router as docs_router

app = FastAPI(
    title="Online Cinema API",
    description="REST API for an online cinema — movies, accounts, cart, orders, payments.",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

api_version_prefix = "/api/v1"

app.include_router(docs_router)
app.include_router(accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"])
app.include_router(profiles_router, prefix=f"{api_version_prefix}/profiles", tags=["profiles"])
app.include_router(movie_router, prefix=f"{api_version_prefix}/theater", tags=["theater"])
