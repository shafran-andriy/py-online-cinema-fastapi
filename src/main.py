from fastapi import FastAPI

from routes import (
    movie_router,
    accounts_router,
    profiles_router,
    notifications_router,
    cart_router,
    admin_router,
)

app = FastAPI(
    title="Movies homework",
    description="Description of project"
)

api_version_prefix = "/api/v1"

app.include_router(accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"])
app.include_router(profiles_router, prefix=f"{api_version_prefix}/profiles", tags=["profiles"])
app.include_router(movie_router, prefix=f"{api_version_prefix}/theater", tags=["theater"])
app.include_router(notifications_router, prefix=f"{api_version_prefix}/notifications", tags=["notifications"])
app.include_router(cart_router, prefix=f"{api_version_prefix}/cart", tags=["cart"])
app.include_router(admin_router, prefix=f"{api_version_prefix}/admin", tags=["admin"])
app = FastAPI(
    title="Online Cinema API",
    description=(
        "REST API for an online cinema platform. "
        "See feature branches for full implementations: "
        "accounts (feature/01-auth), movies (feature/02-movies), "
        "cart (feature/03-cart), orders (feature/04-orders), "
        "payments (feature/05-payments)."
    ),
    version="1.0.0",
)
