from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from database import get_db, MovieModel
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderItemModel, OrderStatusEnum
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
    stmt = (
        select(OrderItemModel)
        .join(OrderModel)
        .where(
            OrderModel.user_id == user_id,
            OrderModel.status == OrderStatusEnum.PAID,
            OrderItemModel.movie_id == movie_id,
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None


@router.get(
    "/",
    response_model=CartSchema,
    summary="Get current user's cart",
    description="""
Returns the shopping cart of the currently authenticated user.

If the cart does not exist yet, it is automatically created and returned empty.

**Response fields:**
- `id` — cart identifier
- `user_id` — owner of the cart
- `items` — list of cart items, each containing:
  - `movie_id` — ID of the movie
  - `movie` — nested movie object with name, price, genres, etc.

**Auth:** Bearer token required.
    """,
)
async def get_cart(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Retrieve the shopping cart for the authenticated user.

    Creates an empty cart automatically if one does not exist.
    Returns a CartSchema with all items and their associated movie data.
    """
    cart = await _get_or_create_cart(db, current_user.id)
    return CartSchema.model_validate(cart)


@router.post(
    "/items/",
    response_model=CartSchema,
    status_code=201,
    summary="Add movie to cart",
    description="""
Adds a movie to the current user's shopping cart.

**Request body:**
```json
{
  "movie_id": 42
}
```

**Validation rules:**
- The movie must exist — `404` if not found.
- The movie must not have been purchased by the user in a paid order — `400`.
- The movie must not already be in the cart — `409`.

**Response:** Updated cart with all items.

**Auth:** Bearer token required.
    """,
)
async def add_to_cart(
    body: CartAddItemSchema,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Add a movie to the authenticated user's cart.

    Args:
        body: CartAddItemSchema containing `movie_id` (int).

    Raises:
        404: Movie with the given ID does not exist.
        400: Movie was already purchased by the user.
        409: Movie is already present in the cart.

    Returns:
        CartSchema: Updated cart with all current items.
    """
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


@router.delete(
    "/items/{movie_id}/",
    response_model=CartSchema,
    summary="Remove movie from cart",
    description="""
Removes a specific movie from the current user's cart.

**Path parameter:**
- `movie_id` (int) — ID of the movie to remove.

Returns `404` if the movie is not present in the cart.

**Response:** Updated cart after removal.

**Auth:** Bearer token required.
    """,
)
async def remove_from_cart(
    movie_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Remove a movie from the authenticated user's cart.

    Args:
        movie_id: ID of the movie to remove.

    Raises:
        404: Movie is not in the cart.

    Returns:
        CartSchema: Updated cart after the item is removed.
    """
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


@router.delete(
    "/",
    status_code=204,
    summary="Clear cart",
    description="""
Removes **all** items from the current user's cart at once.

The cart record itself remains; only its items are deleted.

**Response:** `204 No Content` on success (empty body).

**Auth:** Bearer token required.
    """,
)
async def clear_cart(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Remove all items from the authenticated user's cart.

    The cart itself is preserved; only its CartItem entries are deleted.
    Returns 204 No Content on success.
    """
    cart = await _get_or_create_cart(db, current_user.id)
    await db.execute(delete(CartItemModel).where(CartItemModel.cart_id == cart.id))
    await db.commit()
