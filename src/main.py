from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from routes import (
    movie_router,
    accounts_router,
    profiles_router,
    notifications_router,
    cart_router,
    orders_router,
    payments_router,
    admin_router,
)
from routes.docs import router as docs_router

app = FastAPI(
    title="Online Cinema API",
    description=(
        "REST API for an online cinema platform — movies, accounts, cart, orders, payments.\n\n"
        "**How to authenticate:**\n"
        "1. Register: `POST /api/v1/accounts/register/`\n"
        "2. Activate account (check MailHog at http://localhost:8025 or get token from DB)\n"
        "3. Login: `POST /api/v1/accounts/login/` — copy `access_token`\n"
        "4. Click **Authorize** button above and enter: `Bearer <access_token>`"
    ),
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

api_version_prefix = "/api/v1"

app.include_router(docs_router)
app.include_router(accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"])
app.include_router(profiles_router, prefix=f"{api_version_prefix}/profiles", tags=["profiles"])
app.include_router(movie_router, prefix=f"{api_version_prefix}", tags=["movies"])
app.include_router(notifications_router, prefix=f"{api_version_prefix}/notifications", tags=["notifications"])
app.include_router(cart_router, prefix=f"{api_version_prefix}/cart", tags=["cart"])
app.include_router(orders_router, prefix=f"{api_version_prefix}/orders", tags=["orders"])
app.include_router(payments_router, prefix=f"{api_version_prefix}/payments", tags=["payments"])
app.include_router(admin_router, prefix=f"{api_version_prefix}/admin", tags=["admin"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict) and operation.get("security") is not None:
                operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi  # type: ignore[method-assign]
