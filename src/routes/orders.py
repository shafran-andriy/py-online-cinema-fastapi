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


@router.post("/", response_model=OrderSchema, status_code=201)
async def create_order(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
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
    schema.payment_url = f"/api/v1/payments/{order.id}/"
    return schema


@router.get("/", response_model=list[OrderSchema])
async def list_orders(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
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


@router.get("/{order_id}/", response_model=OrderSchema)
async def get_order(
    order_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = await _load_order(db, order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return OrderSchema.model_validate(order)


@router.patch("/{order_id}/cancel/", response_model=OrderSchema)
async def cancel_order(
    order_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    order = await _load_order(db, order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail="Only pending orders can be canceled.")
    order.status = OrderStatusEnum.CANCELED
    await db.commit()
    order = await _load_order(db, order_id, current_user.id)
    return OrderSchema.model_validate(order)
