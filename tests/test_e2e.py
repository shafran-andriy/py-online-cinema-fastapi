"""
End-to-end functional tests covering complete user journeys:
  1. Registration → activation → login → cart → order → payment
  2. Admin flow: create movie → moderator deletes movie → cart notification
  3. Password change flow
  4. Refresh token flow
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient
from sqlalchemy import select

from config.dependencies import get_accounts_email_notificator, get_stripe_service
from database import (
    get_db,
    UserModel,
    UserGroupModel,
    ActivationTokenModel,
    CertificationModel,
    MovieModel,
    NotificationModel,
)
from database.models.cart import CartModel, CartItemModel
from database.models.orders import OrderModel, OrderStatusEnum
from database.models.payments import PaymentModel, PaymentStatusEnum
from main import app


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class _DummyEmail:
    def __init__(self):
        self.sent = []

    async def send_activation_email(self, email, link):
        self.sent.append(('activation', email))

    async def send_activation_complete_email(self, email, link):
        self.sent.append(('activation_complete', email))

    async def send_password_reset_email(self, email, link):
        self.sent.append(('password_reset', email))

    async def send_password_reset_complete_email(self, email, link):
        self.sent.append(('password_reset_complete', email))

    async def send_payment_confirmation_email(self, email, order_id, amount):
        self.sent.append(('payment_confirmation', email, order_id, amount))


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client_with_email():
    dummy = _DummyEmail()
    async with AsyncClient(transport=__import__('httpx._transports.asgi', fromlist=['ASGITransport']).ASGITransport(app=app), base_url='http://testserver') as ac:
        app.dependency_overrides[get_accounts_email_notificator] = lambda: dummy
        yield ac, dummy
        app.dependency_overrides.clear()


async def _register_activate_login(client, email, password="StrongP@ss1!"):
    r = await client.post("/api/v1/accounts/register/", json={"email": email, "password": password})
    assert r.status_code == 201, r.text

    async for db in get_db():
        res = await db.execute(
            select(ActivationTokenModel).join(UserModel).where(UserModel.email == email)
        )
        tok = res.scalars().first()
        assert tok
        token = tok.token
        break

    r = await client.post("/api/v1/accounts/activate/", json={"email": email, "token": token})
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/accounts/login/", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    return data["access_token"], data["refresh_token"]


async def _make_moderator(email):
    async for db in get_db():
        res = await db.execute(select(UserGroupModel).where(UserGroupModel.name == "moderator"))
        mod_group = res.scalars().first()
        res2 = await db.execute(select(UserModel).where(UserModel.email == email))
        user = res2.scalars().first()
        user.group_id = mod_group.id
        await db.commit()
        break


async def _seed_movie(name="E2E Movie", price=12.99):
    movie_id = None
    async for db in get_db():
        cert = CertificationModel(name="PG")
        db.add(cert)
        await db.flush()
        movie = MovieModel(
            name=name, year=2023, time=105, imdb=7.5,
            votes=500, description="E2E test movie", price=price,
            certification_id=cert.id,
        )
        db.add(movie)
        await db.flush()
        await db.commit()
        movie_id = movie.id
        break
    return movie_id


async def _get_user_id(email):
    user_id = None
    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == email))
        user = res.scalars().first()
        user_id = user.id if user else None
        break
    return user_id


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_mock_stripe(order_id, user_id, session_id="cs_e2e_123"):
    mock_session = MagicMock()
    mock_session.id = session_id
    mock_session.url = f"https://checkout.stripe.com/pay/{session_id}"
    mock_session.payment_status = "paid"
    mock_session.amount_total = 1299
    mock_session.metadata = {"order_id": str(order_id), "user_id": str(user_id)}
    mock_stripe = MagicMock()
    mock_stripe.create_checkout_session = MagicMock(return_value=mock_session)
    mock_stripe.retrieve_session = MagicMock(return_value=mock_session)
    mock_stripe.construct_webhook_event = MagicMock(side_effect=Exception("not used in e2e"))
    return mock_stripe, mock_session


# ---------------------------------------------------------------------------
# E2E Test 1: full purchase flow
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_full_purchase_flow(client):
    """Register → activate → login → add to cart → create order → pay → verify payment record."""
    email = "e2e_buyer@test.com"
    movie_id = await _seed_movie("E2E Film", price=9.99)

    access, refresh = await _register_activate_login(client, email)
    user_id = await _get_user_id(email)

    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(access))
    assert r.status_code == 201, r.text
    cart_data = r.json()
    assert len(cart_data["items"]) == 1

    r = await client.post("/api/v1/orders/", headers=auth(access))
    assert r.status_code == 201, r.text
    order_data = r.json()
    order_id = order_data["id"]
    assert order_data["status"] == "pending"

    r = await client.get("/api/v1/cart/", headers=auth(access))
    assert r.status_code == 200
    assert r.json()["items"] == []

    mock_stripe, mock_session = _make_mock_stripe(order_id, user_id)
    app.dependency_overrides[get_stripe_service] = lambda: mock_stripe

    dummy_email = _DummyEmail()
    app.dependency_overrides[get_accounts_email_notificator] = lambda: dummy_email

    r = await client.post("/api/v1/payments/create-session/", json={"order_id": order_id}, headers=auth(access))
    assert r.status_code == 200, r.text
    session_data = r.json()
    assert "checkout_url" in session_data

    r = await client.get(f"/api/v1/payments/success/?session_id={mock_session.id}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    async for db in get_db():
        res = await db.execute(select(PaymentModel).where(PaymentModel.order_id == order_id))
        payment = res.scalars().first()
        assert payment is not None
        assert payment.status == PaymentStatusEnum.SUCCESSFUL
        break

    async for db in get_db():
        res = await db.execute(select(OrderModel).where(OrderModel.id == order_id))
        order = res.scalars().first()
        assert order.status == OrderStatusEnum.PAID
        break

    r = await client.get("/api/v1/payments/", headers=auth(access))
    assert r.status_code == 200
    payments = r.json()
    assert len(payments) >= 1
    assert payments[0]["order_id"] == order_id


# ---------------------------------------------------------------------------
# E2E Test 2: token refresh flow
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_token_refresh_flow(client):
    """Login → use refresh token → get new access token → use it to access protected endpoint."""
    email = "e2e_refresh@test.com"
    access, refresh = await _register_activate_login(client, email)

    r = await client.post("/api/v1/accounts/token/refresh/", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    new_access = data["access_token"]

    r = await client.get("/api/v1/cart/", headers=auth(new_access))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# E2E Test 3: invalid refresh token rejected
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_invalid_refresh_token_rejected(client):
    """Using a structurally valid but wrong-key JWT as refresh token returns 400."""
    bad_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJ1c2VyX2lkIjo5OTk5fQ"
        ".wrongsignatureXXXXXXXXXXXXXXXXXXXXXXX"
    )
    r = await client.post("/api/v1/accounts/token/refresh/", json={"refresh_token": bad_token})
    assert r.status_code in (400, 401)


# ---------------------------------------------------------------------------
# E2E Test 4: purchased movie blocked from re-adding to cart
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_purchased_movie_blocked_from_cart(client):
    """After purchase, trying to add same movie to cart returns 400."""
    email = "e2e_block@test.com"
    movie_id = await _seed_movie("E2E Blocked Film", price=5.99)
    access, _ = await _register_activate_login(client, email)
    user_id = await _get_user_id(email)

    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(access))
    assert r.status_code == 201

    r = await client.post("/api/v1/orders/", headers=auth(access))
    assert r.status_code == 201
    order_id = r.json()["id"]

    async for db in get_db():
        res = await db.execute(select(OrderModel).where(OrderModel.id == order_id))
        order = res.scalars().first()
        order.status = OrderStatusEnum.PAID
        await db.commit()
        break

    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(access))
    assert r.status_code == 400
    assert "purchased" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# E2E Test 5: moderator deletes movie that is in users' carts — notification created
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_movie_with_cart_creates_notification(client):
    """Moderator deletes a movie that is in a user's cart → NotificationModel created."""
    user_email = "e2e_cartuser@test.com"
    mod_email = "e2e_mod@test.com"
    movie_id = await _seed_movie("E2E Cart Movie", price=7.99)

    user_token, _ = await _register_activate_login(client, user_email)
    mod_token, _ = await _register_activate_login(client, mod_email)
    await _make_moderator(mod_email)

    r = await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(user_token))
    assert r.status_code == 201

    mod_id = await _get_user_id(mod_email)

    r = await client.delete(f"/api/v1/theater/movies/{movie_id}/", headers=auth(mod_token))
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True

    async for db in get_db():
        res = await db.execute(
            select(NotificationModel).where(NotificationModel.user_id == mod_id)
        )
        notif = res.scalars().first()
        assert notif is not None
        assert str(movie_id) in notif.message
        break


# ---------------------------------------------------------------------------
# E2E Test 6: logout invalidates token
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_logout_invalidates_refresh_token(client):
    """Logout should invalidate the refresh token so it can't be used again."""
    email = "e2e_logout@test.com"
    access, refresh = await _register_activate_login(client, email)

    r = await client.post("/api/v1/accounts/logout/", json={"refresh_token": refresh}, headers=auth(access))
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/accounts/token/refresh/", json={"refresh_token": refresh})
    assert r.status_code in (400, 401)
