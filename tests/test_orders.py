"""
Tests for КРОК 4 order endpoints:
  4.1 Models OrderModel / OrderItemModel / OrderStatusEnum
  4.2 POST /api/v1/orders/           — create order from cart
      GET  /api/v1/orders/           — list own orders
      GET  /api/v1/orders/{id}/      — order detail
      PATCH /api/v1/orders/{id}/cancel/ — cancel pending order
  4.3 GET /api/v1/admin/orders/      — moderator view with filters
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import (
    get_db,
    MovieModel,
    CertificationModel,
    UserModel,
    UserGroupModel,
    ActivationTokenModel,
)
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderStatusEnum
from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _register_activate_login(client: AsyncClient, email: str, password="StrongP@ss1!") -> str:
    r = await client.post("/api/v1/accounts/register/", json={"email": email, "password": password})
    assert r.status_code == 201, r.text

    async for db in get_db():
        res = await db.execute(
            select(ActivationTokenModel).join(UserModel).where(UserModel.email == email)
        )
        token_obj = res.scalars().first()
        assert token_obj
        token = token_obj.token
        break

    r = await client.post("/api/v1/accounts/activate/", json={"email": email, "token": token})
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/accounts/login/", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _make_moderator(email: str):
    async for db in get_db():
        res = await db.execute(select(UserGroupModel).where(UserGroupModel.name == "moderator"))
        mod_group = res.scalars().first()
        res2 = await db.execute(select(UserModel).where(UserModel.email == email))
        user = res2.scalars().first()
        user.group_id = mod_group.id
        await db.commit()
        break


async def _seed_movie(name="Order Test Movie", price=15.0) -> int:
    async for db in get_db():
        cert = CertificationModel(name="G")
        db.add(cert)
        await db.flush()
        movie = MovieModel(
            name=name, year=2022, time=100, imdb=7.0,
            votes=100, description="For order tests", price=price,
            certification_id=cert.id,
        )
        db.add(movie)
        await db.flush()
        await db.commit()
        return movie.id


async def _seed_two_movies() -> tuple[int, int]:
    async for db in get_db():
        cert = CertificationModel(name="PG")
        db.add(cert)
        await db.flush()
        m1 = MovieModel(
            name="Order Alpha", year=2020, time=90, imdb=6.0,
            votes=100, description="Alpha", price=9.99, certification_id=cert.id,
        )
        m2 = MovieModel(
            name="Order Beta", year=2021, time=110, imdb=7.0,
            votes=150, description="Beta", price=14.99, certification_id=cert.id,
        )
        db.add_all([m1, m2])
        await db.flush()
        await db.commit()
        return m1.id, m2.id


async def _force_pay_order(order_id: int):
    """Directly set an order to PAID status (simulates Stripe webhook)."""
    async for db in get_db():
        res = await db.execute(select(OrderModel).where(OrderModel.id == order_id))
        order = res.scalars().first()
        order.status = OrderStatusEnum.PAID
        await db.commit()
        break


async def _force_add_to_cart(user_id: int, movie_id: int):
    """Bypass the cart endpoint guard and insert a CartItem directly into the DB."""
    async for db in get_db():
        res = await db.execute(select(CartModel).where(CartModel.user_id == user_id))
        cart = res.scalars().first()
        if not cart:
            cart = CartModel(user_id=user_id)
            db.add(cart)
            await db.flush()
        db.add(CartItemModel(cart_id=cart.id, movie_id=movie_id))
        await db.commit()
        break


async def _get_user_id(email: str) -> int:
    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == email))
        return res.scalars().first().id


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 4.2 POST /orders/ — create order from cart
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_order_from_cart(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_basic@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r = await client.post("/api/v1/orders/", headers=auth(token))

    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "pending"
    assert len(data["items"]) == 1
    assert data["items"][0]["movie_id"] == movie_id
    assert data["total_amount"] == 15.0
    assert data["payment_url"] is not None
    assert str(data["id"]) in data["payment_url"]


@pytest.mark.anyio
async def test_create_order_clears_cart(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_clearcart@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    await client.post("/api/v1/orders/", headers=auth(token))

    cart_r = await client.get("/api/v1/cart/", headers=auth(token))
    assert cart_r.json()["items"] == []


@pytest.mark.anyio
async def test_create_order_empty_cart_returns_400(client):
    token = await _register_activate_login(client, "order_empty@test.com")
    r = await client.post("/api/v1/orders/", headers=auth(token))
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_order_requires_auth(client):
    r = await client.post("/api/v1/orders/")
    assert r.status_code == 403  # HTTPBearer returns 403 when no token


@pytest.mark.anyio
async def test_create_order_excludes_purchased_movies(client):
    m1_id, m2_id = await _seed_two_movies()
    token = await _register_activate_login(client, "order_excl@test.com")

    # First order: buy m1
    await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=auth(token))
    r1 = await client.post("/api/v1/orders/", headers=auth(token))
    assert r1.status_code == 201
    order1_id = r1.json()["id"]

    # Mark order as PAID
    await _force_pay_order(order1_id)

    # Second cart: m1 (purchased) + m2 (not purchased)
    await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=auth(token))
    await client.post("/api/v1/cart/items/", json={"movie_id": m2_id}, headers=auth(token))
    r2 = await client.post("/api/v1/orders/", headers=auth(token))

    assert r2.status_code == 201
    order_movie_ids = [item["movie_id"] for item in r2.json()["items"]]
    assert m1_id not in order_movie_ids  # excluded because purchased
    assert m2_id in order_movie_ids


@pytest.mark.anyio
async def test_create_order_all_purchased_returns_400(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_allpurch@test.com")
    user_id = await _get_user_id("order_allpurch@test.com")

    # Order and pay for the movie
    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r1 = await client.post("/api/v1/orders/", headers=auth(token))
    await _force_pay_order(r1.json()["id"])

    # Bypass cart guard — directly insert already-purchased movie back into the cart
    await _force_add_to_cart(user_id, movie_id)

    # All cart movies are purchased → 400
    r2 = await client.post("/api/v1/orders/", headers=auth(token))
    assert r2.status_code == 400
    assert "already purchased" in r2.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_order_pending_movie_returns_409(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_pending409@test.com")

    # First order: creates pending order with movie_id
    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r1 = await client.post("/api/v1/orders/", headers=auth(token))
    assert r1.status_code == 201
    assert r1.json()["status"] == "pending"

    # Try to order same movie again (it's in a pending order)
    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r2 = await client.post("/api/v1/orders/", headers=auth(token))
    assert r2.status_code == 409
    assert "pending" in r2.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_order_total_amount_correct(client):
    m1_id, m2_id = await _seed_two_movies()
    token = await _register_activate_login(client, "order_total@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=auth(token))
    await client.post("/api/v1/cart/items/", json={"movie_id": m2_id}, headers=auth(token))
    r = await client.post("/api/v1/orders/", headers=auth(token))

    assert r.status_code == 201
    # 9.99 + 14.99 = 24.98
    assert abs(r.json()["total_amount"] - 24.98) < 0.01


# ---------------------------------------------------------------------------
# 4.2 GET /orders/ — list own orders
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_orders_empty(client):
    token = await _register_activate_login(client, "order_listempty@test.com")
    r = await client.get("/api/v1/orders/", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.anyio
async def test_list_orders_after_checkout(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_list@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    await client.post("/api/v1/orders/", headers=auth(token))

    r = await client.get("/api/v1/orders/", headers=auth(token))
    assert r.status_code == 200
    orders = r.json()
    assert len(orders) == 1
    assert orders[0]["status"] == "pending"


@pytest.mark.anyio
async def test_list_orders_requires_auth(client):
    r = await client.get("/api/v1/orders/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_orders_are_isolated_per_user(client):
    movie_id = await _seed_movie()
    token1 = await _register_activate_login(client, "order_iso1@test.com")
    token2 = await _register_activate_login(client, "order_iso2@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token1))
    await client.post("/api/v1/orders/", headers=auth(token1))

    r = await client.get("/api/v1/orders/", headers=auth(token2))
    assert r.json() == []


# ---------------------------------------------------------------------------
# 4.2 GET /orders/{id}/ — order detail
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_order_detail(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_detail@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    order_r = await client.post("/api/v1/orders/", headers=auth(token))
    order_id = order_r.json()["id"]

    r = await client.get(f"/api/v1/orders/{order_id}/", headers=auth(token))
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == order_id
    assert len(data["items"]) == 1
    assert data["items"][0]["movie_id"] == movie_id


@pytest.mark.anyio
async def test_get_order_not_found(client):
    token = await _register_activate_login(client, "order_notfound@test.com")
    r = await client.get("/api/v1/orders/99999/", headers=auth(token))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_get_order_other_user_not_found(client):
    movie_id = await _seed_movie()
    token1 = await _register_activate_login(client, "order_priv1@test.com")
    token2 = await _register_activate_login(client, "order_priv2@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token1))
    order_r = await client.post("/api/v1/orders/", headers=auth(token1))
    order_id = order_r.json()["id"]

    r = await client.get(f"/api/v1/orders/{order_id}/", headers=auth(token2))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 4.2 PATCH /orders/{id}/cancel/ — cancel pending order
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cancel_pending_order(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_cancel@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    order_r = await client.post("/api/v1/orders/", headers=auth(token))
    order_id = order_r.json()["id"]

    r = await client.patch(f"/api/v1/orders/{order_id}/cancel/", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


@pytest.mark.anyio
async def test_cancel_paid_order_returns_400(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_cancelpaid@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    order_r = await client.post("/api/v1/orders/", headers=auth(token))
    order_id = order_r.json()["id"]
    await _force_pay_order(order_id)

    r = await client.patch(f"/api/v1/orders/{order_id}/cancel/", headers=auth(token))
    assert r.status_code == 400
    assert "pending" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_cancel_order_not_found(client):
    token = await _register_activate_login(client, "order_cancelnotfound@test.com")
    r = await client.patch("/api/v1/orders/99999/cancel/", headers=auth(token))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_cancel_requires_auth(client):
    r = await client.patch("/api/v1/orders/1/cancel/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_canceled_movie_can_be_reordered(client):
    """After cancel, movie leaves pending state — can be ordered again."""
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_reorder@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r1 = await client.post("/api/v1/orders/", headers=auth(token))
    order_id = r1.json()["id"]

    await client.patch(f"/api/v1/orders/{order_id}/cancel/", headers=auth(token))

    # Now add to cart and order again
    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r2 = await client.post("/api/v1/orders/", headers=auth(token))
    assert r2.status_code == 201
    assert r2.json()["status"] == "pending"


# ---------------------------------------------------------------------------
# 4.2 Cart: purchased movie cannot be added (400)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cart_blocks_adding_purchased_movie(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "order_cartblock@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    r1 = await client.post("/api/v1/orders/", headers=auth(token))
    await _force_pay_order(r1.json()["id"])

    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    assert r.status_code == 400
    assert "already purchased" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4.3 GET /admin/orders/ — moderator sees all orders with filters
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_orders_requires_auth(client):
    r = await client.get("/api/v1/admin/orders/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_orders_requires_moderator(client):
    token = await _register_activate_login(client, "order_admnomod@test.com")
    r = await client.get("/api/v1/admin/orders/", headers=auth(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_orders_as_moderator(client):
    movie_id = await _seed_movie()
    user_token = await _register_activate_login(client, "order_admusr@test.com")
    mod_token = await _register_activate_login(client, "order_admmod@test.com")
    await _make_moderator("order_admmod@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(user_token))
    await client.post("/api/v1/orders/", headers=auth(user_token))

    r = await client.get("/api/v1/admin/orders/", headers=auth(mod_token))
    assert r.status_code == 200
    orders = r.json()
    assert isinstance(orders, list)
    assert len(orders) >= 1
    movie_ids = [item["movie_id"] for o in orders for item in o["items"]]
    assert movie_id in movie_ids


@pytest.mark.anyio
async def test_admin_orders_filter_by_status(client):
    movie_id = await _seed_movie()
    user_token = await _register_activate_login(client, "order_filtstat@test.com")
    mod_token = await _register_activate_login(client, "order_filtstatmod@test.com")
    await _make_moderator("order_filtstatmod@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(user_token))
    r1 = await client.post("/api/v1/orders/", headers=auth(user_token))
    order_id = r1.json()["id"]
    await _force_pay_order(order_id)

    r_paid = await client.get("/api/v1/admin/orders/?status=paid", headers=auth(mod_token))
    assert r_paid.status_code == 200
    paid_orders = r_paid.json()
    assert all(o["status"] == "paid" for o in paid_orders)

    r_pending = await client.get("/api/v1/admin/orders/?status=pending", headers=auth(mod_token))
    assert r_pending.status_code == 200
    assert all(o["status"] == "pending" for o in r_pending.json())


@pytest.mark.anyio
async def test_admin_orders_filter_by_user_id(client):
    movie_id = await _seed_movie()
    u1_token = await _register_activate_login(client, "order_filtusr1@test.com")
    u2_token = await _register_activate_login(client, "order_filtusr2@test.com")
    mod_token = await _register_activate_login(client, "order_filtusrmod@test.com")
    await _make_moderator("order_filtusrmod@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(u1_token))
    await client.post("/api/v1/orders/", headers=auth(u1_token))

    # get u1 user_id from their order
    all_r = await client.get("/api/v1/admin/orders/", headers=auth(mod_token))
    u1_orders = [o for o in all_r.json() if o["items"] and o["items"][0]["movie_id"] == movie_id]
    u1_user_id = u1_orders[0]["user_id"]

    r = await client.get(f"/api/v1/admin/orders/?user_id={u1_user_id}", headers=auth(mod_token))
    assert r.status_code == 200
    assert all(o["user_id"] == u1_user_id for o in r.json())


@pytest.mark.anyio
async def test_admin_orders_empty_when_none(client):
    mod_token = await _register_activate_login(client, "order_admempty@test.com")
    await _make_moderator("order_admempty@test.com")

    r = await client.get("/api/v1/admin/orders/", headers=auth(mod_token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)
