from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models.cart import CartModel, CartItemModel
from schemas.cart import CartSchema, CartAddItemSchema
from security.deps import get_current_user

router = APIRouter()


async def _load_cart(db, user_id: int) -> CartModel:
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


async def _get_or_create_cart(db, user_id: int) -> CartModel:
    cart = await _load_cart(db, user_id)
    if not cart:
        cart = CartModel(user_id=user_id)
        db.add(cart)
        await db.commit()
        cart = await _load_cart(db, user_id)
    return cart


async def _is_movie_purchased(db, movie_id: int, user_id: int) -> bool:
    # stub — will check OrderItemModel once feature/04-orders is merged
    return False


@router.get("/", response_model=CartSchema)
async def get_cart(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    cart = await _get_or_create_cart(db, current_user.id)
    return CartSchema.model_validate(cart)


@router.post("/items/", response_model=CartSchema, status_code=201)
async def add_to_cart(
    body: CartAddItemSchema,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    movie = await db.get(MovieModel, body.movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found.")

    if await _is_movie_purchased(db, body.movie_id, current_user.id):
        raise HTTPException(status_code=400, detail="You have already purchased this movie.")

    cart = await _get_or_create_cart(db, current_user.id)

    already_in_cart = any(item.movie_id == body.movie_id for item in cart.items)
    if already_in_cart:
        raise HTTPException(status_code=409, detail="Movie is already in the cart.")

    db.add(CartItemModel(cart_id=cart.id, movie_id=body.movie_id))
    await db.commit()

    cart = await _load_cart(db, current_user.id)
    return CartSchema.model_validate(cart)


@router.delete("/items/{movie_id}/", response_model=CartSchema)
async def remove_from_cart(
    movie_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    cart = await _get_or_create_cart(db, current_user.id)

    item = next((i for i in cart.items if i.movie_id == movie_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Movie not in cart.")

    await db.execute(
        delete(CartItemModel).where(
            CartItemModel.cart_id == cart.id,
            CartItemModel.movie_id == movie_id,
        )
    )
    await db.commit()

    cart = await _load_cart(db, current_user.id)
    return CartSchema.model_validate(cart)


@router.delete("/", status_code=204)
async def clear_cart(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    cart = await _get_or_create_cart(db, current_user.id)
    await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
    await db.commit()
