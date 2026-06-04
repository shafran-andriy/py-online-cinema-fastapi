"""
Tests for КРОК 3 cart endpoints:
  3.1 Models CartModel / CartItemModel
  3.2 GET  /api/v1/cart/                       — view cart (creates if absent)
      POST /api/v1/cart/items/                  — add movie
      DELETE /api/v1/cart/items/{movie_id}/     — remove movie
      DELETE /api/v1/cart/                      — clear cart
  3.3 GET  /api/v1/admin/carts/                 — moderator view of all carts
"""

import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import (
    get_db,
    MovieModel,
    CertificationModel,
    UserModel,
    UserGroupModel,
)
from main import app
from security.deps import require_moderator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _create_movie(db_session, cert_name="G", movie_name="Cart Test Movie") -> int:
    cert = CertificationModel(name=cert_name)
    db_session.add(cert)
    await db_session.flush()

    movie = MovieModel(
        name=movie_name, year=2021, time=100, imdb=7.5,
        votes=200, description="For cart tests", price=12.99,
        certification_id=cert.id,
    )
    db_session.add(movie)
    await db_session.flush()
    await db_session.commit()
    return movie.id


async def _seed_movie() -> int:
    async for db in get_db():
        movie_id = await _create_movie(db)
        return movie_id


async def _seed_two_movies() -> tuple[int, int]:
    async for db in get_db():
        cert = CertificationModel(name="PG")
        db.add(cert)
        await db.flush()

        m1 = MovieModel(
            name="Movie Alpha", year=2020, time=90, imdb=6.0,
            votes=100, description="Alpha", price=9.99, certification_id=cert.id,
        )
        m2 = MovieModel(
            name="Movie Beta", year=2021, time=110, imdb=7.0,
            votes=150, description="Beta", price=14.99, certification_id=cert.id,
        )
        db.add(m1)
        db.add(m2)
        await db.flush()
        await db.commit()
        return m1.id, m2.id


async def _register_activate_login(client: AsyncClient, email: str, password="StrongP@ss1!") -> str:
    r = await client.post("/api/v1/accounts/register/", json={"email": email, "password": password})
    assert r.status_code == 201, r.text

    async for db in get_db():
        from database import ActivationTokenModel
        res = await db.execute(
            select(ActivationTokenModel).join(UserModel).where(UserModel.email == email)
        )
        token_obj = res.scalars().first()
        assert token_obj, "Activation token not created"
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


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 3.2 GET /cart/ — returns empty cart on first call (auto-creates)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_cart_creates_empty(client):
    token = await _register_activate_login(client, "cart_get@test.com")
    r = await client.get("/api/v1/cart/", headers=auth_headers(token))
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["items"] == []


@pytest.mark.anyio
async def test_get_cart_requires_auth(client):
    r = await client.get("/api/v1/cart/")
    assert r.status_code == 403  # HTTPBearer returns 403 when no token provided


# ---------------------------------------------------------------------------
# 3.2 POST /cart/items/ — add movie
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_add_movie_to_cart(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "cart_add@test.com")

    r = await client.post(
        "/api/v1/cart/items/",
        json={"movie_id": movie_id},
        headers=auth_headers(token),
    )
    assert r.status_code == 201
    data = r.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["movie_id"] == movie_id
    assert item["movie"]["name"] == "Cart Test Movie"
    assert item["movie"]["price"] == 12.99
    assert item["movie"]["year"] == 2021


@pytest.mark.anyio
async def test_add_nonexistent_movie_to_cart(client):
    token = await _register_activate_login(client, "cart_nofilm@test.com")
    r = await client.post(
        "/api/v1/cart/items/",
        json={"movie_id": 99999},
        headers=auth_headers(token),
    )
    assert r.status_code == 404


@pytest.mark.anyio
async def test_add_duplicate_movie_returns_409(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "cart_dup@test.com")
    headers = auth_headers(token)

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=headers)
    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=headers)
    assert r.status_code == 409
    assert "already in the cart" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_add_movie_requires_auth(client):
    movie_id = await _seed_movie()
    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id})
    assert r.status_code == 403  # HTTPBearer returns 403 when no token provided


@pytest.mark.anyio
async def test_add_two_movies_to_cart(client):
    m1_id, m2_id = await _seed_two_movies()
    token = await _register_activate_login(client, "cart_two@test.com")
    headers = auth_headers(token)

    r1 = await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=headers)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/cart/items/", json={"movie_id": m2_id}, headers=headers)
    assert r2.status_code == 201
    assert len(r2.json()["items"]) == 2


# ---------------------------------------------------------------------------
# 3.2 DELETE /cart/items/{movie_id}/ — remove one item
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_remove_movie_from_cart(client):
    movie_id = await _seed_movie()
    token = await _register_activate_login(client, "cart_rem@test.com")
    headers = auth_headers(token)

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=headers)

    r = await client.delete(f"/api/v1/cart/items/{movie_id}/", headers=headers)
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.anyio
async def test_remove_movie_not_in_cart_returns_404(client):
    token = await _register_activate_login(client, "cart_rem404@test.com")
    r = await client.delete("/api/v1/cart/items/99999/", headers=auth_headers(token))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_remove_one_of_two_movies(client):
    m1_id, m2_id = await _seed_two_movies()
    token = await _register_activate_login(client, "cart_remone@test.com")
    headers = auth_headers(token)

    await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=headers)
    await client.post("/api/v1/cart/items/", json={"movie_id": m2_id}, headers=headers)

    r = await client.delete(f"/api/v1/cart/items/{m1_id}/", headers=headers)
    assert r.status_code == 200
    remaining = [item["movie_id"] for item in r.json()["items"]]
    assert m1_id not in remaining
    assert m2_id in remaining


# ---------------------------------------------------------------------------
# 3.2 DELETE /cart/ — clear cart
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_cart(client):
    m1_id, m2_id = await _seed_two_movies()
    token = await _register_activate_login(client, "cart_clear@test.com")
    headers = auth_headers(token)

    await client.post("/api/v1/cart/items/", json={"movie_id": m1_id}, headers=headers)
    await client.post("/api/v1/cart/items/", json={"movie_id": m2_id}, headers=headers)

    r = await client.delete("/api/v1/cart/", headers=headers)
    assert r.status_code == 204

    r2 = await client.get("/api/v1/cart/", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["items"] == []


@pytest.mark.anyio
async def test_clear_empty_cart_ok(client):
    token = await _register_activate_login(client, "cart_clearemp@test.com")
    r = await client.delete("/api/v1/cart/", headers=auth_headers(token))
    assert r.status_code == 204


@pytest.mark.anyio
async def test_clear_cart_requires_auth(client):
    r = await client.delete("/api/v1/cart/")
    assert r.status_code == 403  # HTTPBearer returns 403 when no token provided


# ---------------------------------------------------------------------------
# Cart isolation between users
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_carts_are_isolated_per_user(client):
    movie_id = await _seed_movie()
    token1 = await _register_activate_login(client, "cart_u1@test.com")
    token2 = await _register_activate_login(client, "cart_u2@test.com")

    await client.post(
        "/api/v1/cart/items/",
        json={"movie_id": movie_id},
        headers=auth_headers(token1),
    )

    r = await client.get("/api/v1/cart/", headers=auth_headers(token2))
    assert r.status_code == 200
    assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# 3.3 GET /admin/carts/ — moderator sees all carts
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_carts_requires_auth(client):
    r = await client.get("/api/v1/admin/carts/")
    assert r.status_code == 403  # HTTPBearer returns 403 when no token provided


@pytest.mark.anyio
async def test_admin_carts_requires_moderator(client):
    token = await _register_activate_login(client, "cart_normaluser@test.com")
    r = await client.get("/api/v1/admin/carts/", headers=auth_headers(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_carts_as_moderator(client):
    movie_id = await _seed_movie()
    user_token = await _register_activate_login(client, "cart_reguser@test.com")
    mod_token = await _register_activate_login(client, "cart_mod@test.com")
    await _make_moderator("cart_mod@test.com")

    # regular user adds a movie
    await client.post(
        "/api/v1/cart/items/",
        json={"movie_id": movie_id},
        headers=auth_headers(user_token),
    )

    r = await client.get("/api/v1/admin/carts/", headers=auth_headers(mod_token))
    assert r.status_code == 200
    carts = r.json()
    assert isinstance(carts, list)
    # at least the regular user's cart is present
    movie_ids_in_carts = [
        item["movie_id"]
        for cart in carts
        for item in cart["items"]
    ]
    assert movie_id in movie_ids_in_carts


@pytest.mark.anyio
async def test_admin_carts_empty_list_when_no_carts(client):
    mod_token = await _register_activate_login(client, "cart_modempty@test.com")
    await _make_moderator("cart_modempty@test.com")

    r = await client.get("/api/v1/admin/carts/", headers=auth_headers(mod_token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)
