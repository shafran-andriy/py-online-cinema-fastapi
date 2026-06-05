from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel, NotificationModel, NotificationTypeEnum
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderItemModel, OrderStatusEnum
from schemas.orders import OrderSchema
from security.deps import get_current_user

router = APIRouter()


async def _load_order(db, order_id: int, user_id: int) -> OrderModel | None:
    stmt = (
        select(OrderModel)
        .options(
            selectinload(OrderModel.items)
            .selectinload(OrderItemModel.movie)
            .selectinload(MovieModel.genres)
        )
        .where(OrderModel.id == order_id, OrderModel.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _load_cart_with_items(db, user_id: int) -> CartModel | None:
    stmt = (
        select(CartModel)
        .options(
            selectinload(CartModel.items)
            .selectinload(CartItemModel.movie)
            .selectinload(MovieModel.genres)
        )
        .where(CartModel.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_paid_movie_ids(db, user_id: int) -> set[int]:
    stmt = (
        select(OrderItemModel.movie_id)
        .join(OrderModel)
        .where(OrderModel.user_id == user_id, OrderModel.status == OrderStatusEnum.PAID)
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


async def _get_pending_movie_ids(db, user_id: int) -> set[int]:
    stmt = (
        select(OrderItemModel.movie_id)
        .join(OrderModel)
        .where(OrderModel.user_id == user_id, OrderModel.status == OrderStatusEnum.PENDING)
    )
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


@router.post(
    "/",
    response_model=OrderSchema,
    status_code=201,
    summary="Create order from cart",
    description="""
Creates a new order from all eligible items in the user's cart.

**Business rules:**
- Cart must not be empty — `400`.
- Movies already purchased (in a PAID order) are **skipped** and a notification is created for the user.
- Movies already in a PENDING order cause a `409` conflict.
- If all cart items are excluded (already purchased), returns `400`.

**Behavior on success:**
- A new order with status `PENDING` is created.
- Cart items are cleared after order creation.
- Response includes a `payment_url` pointing to `POST /api/v1/payments/create-session/`.

**Response fields (OrderSchema):**
- `id` — order ID
- `status` — `pending` | `paid` | `canceled`
- `total_amount` — sum of prices at time of order
- `items` — list of ordered movies with `price_at_order`
- `payment_url` — URL to proceed to payment

**Auth:** Bearer token required.
    """,
)
async def create_order(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Convert the user's cart into a PENDING order.

    Already-purchased movies are excluded and the user is notified.
    Movies in an existing PENDING order cause a 409 error.
    Cart is cleared after successful order creation.

    Returns:
        OrderSchema: The newly created order with payment_url.
    """
    cart = await _load_cart_with_items(db, current_user.id)
    if not cart or not cart.items:
        raise HTTPException(status_code=400, detail="Cart is empty.")

    paid_ids = await _get_paid_movie_ids(db, current_user.id)
    pending_ids = await _get_pending_movie_ids(db, current_user.id)

    orderable = []
    for item in cart.items:
        if item.movie_id in paid_ids:
            db.add(NotificationModel(
                user_id=current_user.id,
                type=NotificationTypeEnum.COMMENT,
                related_id=item.movie_id,
                message=f"Movie '{item.movie.name}' is already purchased and was excluded from your order.",
            ))
            continue
        if item.movie_id in pending_ids:
            raise HTTPException(
                status_code=409,
                detail=f"Movie '{item.movie.name}' is already in a pending order.",
            )
        orderable.append(item)

    if not orderable:
        raise HTTPException(status_code=400, detail="All movies in the cart are already purchased.")

    total = sum(Decimal(str(i.movie.price)) for i in orderable)
    order = OrderModel(
        user_id=current_user.id,
        status=OrderStatusEnum.PENDING,
        total_amount=total,
    )
    db.add(order)
    await db.flush()

    for item in orderable:
        db.add(OrderItemModel(
            order_id=order.id,
            movie_id=item.movie_id,
            price_at_order=Decimal(str(item.movie.price)),
        ))

    await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
    await db.commit()

    order = await _load_order(db, order.id, current_user.id)
    schema = OrderSchema.model_validate(order)
    schema.payment_url = "/api/v1/payments/create-session/"
    return schema


@router.get(
    "/",
    response_model=list[OrderSchema],
    summary="List my orders",
    description="""
Returns all orders placed by the currently authenticated user, sorted by creation date (newest first).

Each order includes its items with movie details and the price at the time of ordering.

**Possible statuses:**
- `pending` — order created, awaiting payment
- `paid` — payment successful
- `canceled` — order was canceled by the user

**Auth:** Bearer token required.
    """,
)
async def list_orders(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Retrieve all orders for the authenticated user.

    Sorted by created_at descending (newest first).
    Each order includes its items with movie and genre data.

    Returns:
        list[OrderSchema]: All orders belonging to the current user.
    """
    stmt = (
        select(OrderModel)
        .options(
            selectinload(OrderModel.items)
            .selectinload(OrderItemModel.movie)
            .selectinload(MovieModel.genres)
        )
        .where(OrderModel.user_id == current_user.id)
        .order_by(OrderModel.created_at.desc())
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    orders = result.scalars().all()
    return [OrderSchema.model_validate(o) for o in orders]


@router.get(
    "/{order_id}/",
    response_model=OrderSchema,
    summary="Get order detail",
    description="""
Returns the full details of a specific order by ID.

**Path parameter:**
- `order_id` (int) — ID of the order to retrieve.

Returns `404` if the order does not exist or does not belong to the current user.

**Auth:** Bearer token required.
    """,
)
async def get_order(
    order_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Retrieve a single order by ID for the authenticated user.

    Args:
        order_id: Primary key of the order.

    Raises:
        404: Order not found or belongs to another user.

    Returns:
        OrderSchema: Full order detail with items.
    """
    order = await _load_order(db, order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return OrderSchema.model_validate(order)


@router.patch(
    "/{order_id}/cancel/",
    response_model=OrderSchema,
    summary="Cancel order",
    description="""
Cancels a pending order. Only orders with status `pending` can be canceled.

**Path parameter:**
- `order_id` (int) — ID of the order to cancel.

**Error responses:**
- `404` — order not found or belongs to another user.
- `400` — order is not in `pending` status (already paid or already canceled).

After cancellation the order status changes to `canceled`.
Canceled items are returned to availability but the cart is **not** restored automatically.

**Auth:** Bearer token required.
    """,
)
async def cancel_order(
    order_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Cancel a pending order belonging to the authenticated user.

    Args:
        order_id: Primary key of the order to cancel.

    Raises:
        404: Order not found or belongs to another user.
        400: Order status is not PENDING (cannot cancel paid/canceled orders).

    Returns:
        OrderSchema: Updated order with status 'canceled'.
    """
    order = await _load_order(db, order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail="Only pending orders can be canceled.")
    order.status = OrderStatusEnum.CANCELED
    await db.commit()
    order = await _load_order(db, order_id, current_user.id)
    return OrderSchema.model_validate(order)
