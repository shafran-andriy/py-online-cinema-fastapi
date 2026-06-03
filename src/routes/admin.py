from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models.cart import CartModel, CartItemModel
from schemas.cart import CartSchema
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
