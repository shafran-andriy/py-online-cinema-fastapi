from fastapi import FastAPI

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
