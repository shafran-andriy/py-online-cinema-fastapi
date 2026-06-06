from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderItemModel, OrderStatusEnum
from database.models.payments import PaymentModel, PaymentStatusEnum
from schemas.cart import CartSchema
from schemas.orders import OrderSchema
from schemas.payments import PaymentSchema
from security.deps import require_moderator

router = APIRouter()


@router.get(
    "/carts/",
    response_model=list[CartSchema],
    summary="List all users' carts",
    description="""
Returns the shopping carts of **all** registered users.

Intended for moderators to inspect cart contents for analysis or troubleshooting
(e.g. verifying what users have in their carts before a movie is deleted).

Each cart includes:
- `user_id` — owner of the cart
- `items` — list of movies in the cart with full movie details and genres

**Auth:** Moderator or Admin role required.
    """,
)
async def list_all_carts(
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
    """
    Retrieve all shopping carts across all users.

    Only accessible by moderators and admins.
    Each cart is fully loaded with its items and associated movie/genre data.

    Returns:
        list[CartSchema]: All carts in the system.
    """
    stmt = (
        select(CartModel)
        .options(
            selectinload(CartModel.items)
            .selectinload(CartItemModel.movie)
            .selectinload(MovieModel.genres)
        )
    )
    result = await db.execute(stmt)
    carts = result.scalars().all()
    return [CartSchema.model_validate(c) for c in carts]


@router.get(
    "/orders/",
    response_model=list[OrderSchema],
    summary="List all orders (admin view)",
    description="""
Returns orders from **all** users with optional filters. Sorted by creation date (newest first).

**Query parameters (all optional):**
- `user_id` (int) — filter by a specific user's ID
- `status` (str) — filter by order status: `PENDING` | `PAID` | `CANCELED`
- `date_from` (date, format `YYYY-MM-DD`) — include orders created on or after this date
- `date_to` (date, format `YYYY-MM-DD`) — include orders created on or before this date

**Example:**
```
GET /api/v1/admin/orders/?status=PENDING&date_from=2024-01-01
```

**Auth:** Moderator or Admin role required.
    """,
)
async def list_all_orders(
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    status: Optional[OrderStatusEnum] = Query(None, description="Filter by order status: PENDING, PAID, CANCELED"),
    date_from: Optional[date] = Query(None, description="Include orders from this date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Include orders up to this date (YYYY-MM-DD)"),
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
    """
    Retrieve all orders in the system with optional filtering.

    Args:
        user_id: Filter to a specific user's orders.
        status: Filter by OrderStatusEnum (PENDING, PAID, CANCELED).
        date_from: Return only orders created on or after this date.
        date_to: Return only orders created on or before this date.

    Returns:
        list[OrderSchema]: Filtered list of all orders, newest first.
    """
    stmt = (
        select(OrderModel)
        .options(
            selectinload(OrderModel.items)
            .selectinload(OrderItemModel.movie)
            .selectinload(MovieModel.genres)
        )
        .order_by(OrderModel.created_at.desc())
    )
    if user_id is not None:
        stmt = stmt.where(OrderModel.user_id == user_id)
    if status is not None:
        stmt = stmt.where(OrderModel.status == status)
    if date_from is not None:
        stmt = stmt.where(OrderModel.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(OrderModel.created_at <= date_to)

    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [OrderSchema.model_validate(o) for o in orders]


@router.get(
    "/payments/",
    response_model=list[PaymentSchema],
    summary="List all payments (admin view)",
    description="""
Returns payment records from **all** users with optional filters. Sorted by creation date (newest first).

**Query parameters (all optional):**
- `user_id` (int) — filter by a specific user's ID
- `status` (str) — filter by payment status: `SUCCESSFUL` | `CANCELED` | `REFUNDED`
- `date_from` (date, format `YYYY-MM-DD`) — include payments made on or after this date
- `date_to` (date, format `YYYY-MM-DD`) — include payments made on or before this date

**Example:**
```
GET /api/v1/admin/payments/?status=SUCCESSFUL&user_id=5
```

Each payment includes:
- `amount` — total amount charged
- `external_payment_id` — Stripe session ID
- `items` — individual movie prices at time of payment

**Auth:** Moderator or Admin role required.
    """,
)
async def list_all_payments(
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    status: Optional[PaymentStatusEnum] = Query(None, description="Filter by status: SUCCESSFUL, CANCELED, REFUNDED"),
    date_from: Optional[date] = Query(None, description="Include payments from this date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Include payments up to this date (YYYY-MM-DD)"),
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
    """
    Retrieve all payment records in the system with optional filtering.

    Args:
        user_id: Filter to a specific user's payments.
        status: Filter by PaymentStatusEnum (SUCCESSFUL, CANCELED, REFUNDED).
        date_from: Return only payments created on or after this date.
        date_to: Return only payments created on or before this date.

    Returns:
        list[PaymentSchema]: Filtered list of all payments, newest first.
    """
    stmt = (
        select(PaymentModel)
        .options(selectinload(PaymentModel.items))
        .order_by(PaymentModel.created_at.desc())
    )
    if user_id is not None:
        stmt = stmt.where(PaymentModel.user_id == user_id)
    if status is not None:
        stmt = stmt.where(PaymentModel.status == status)
    if date_from is not None:
        stmt = stmt.where(PaymentModel.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(PaymentModel.created_at <= date_to)

    result = await db.execute(stmt)
    payments = result.scalars().all()
    return [PaymentSchema.model_validate(p) for p in payments]
