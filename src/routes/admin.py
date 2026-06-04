from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderItemModel, OrderStatusEnum
from database.models.payments import PaymentModel, PaymentItemModel, PaymentStatusEnum
from schemas.cart import CartSchema
from schemas.orders import OrderSchema
from schemas.payments import PaymentSchema
from security.deps import require_moderator

router = APIRouter()


@router.get("/carts/", response_model=list[CartSchema])
async def list_all_carts(
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
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


@router.get("/orders/", response_model=list[OrderSchema])
async def list_all_orders(
    user_id: Optional[int] = Query(None),
    status: Optional[OrderStatusEnum] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
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


@router.get("/payments/", response_model=list[PaymentSchema])
async def list_all_payments(
    user_id: Optional[int] = Query(None),
    status: Optional[PaymentStatusEnum] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db=Depends(get_db),
    _mod=Depends(require_moderator),
):
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
