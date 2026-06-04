"""
Tests for КРОК 5 payment endpoints:
  5.1 Stripe Integration
      POST /api/v1/payments/create-session/ — create Stripe Checkout Session
      GET  /api/v1/payments/success/        — handle Stripe success redirect
      GET  /api/v1/payments/cancel/         — handle Stripe cancel redirect
  5.2 POST /api/v1/payments/webhook/        — Stripe webhook
  5.3 Models PaymentModel / PaymentItemModel / PaymentStatusEnum
  5.4 GET  /api/v1/payments/               — list own payments
  5.5 GET  /api/v1/admin/payments/         — moderator view with filters
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient
from sqlalchemy import select

from config.dependencies import get_stripe_service, get_accounts_email_notificator
from database import (
    get_db,
    MovieModel,
    CertificationModel,
    UserModel,
    UserGroupModel,
    ActivationTokenModel,
)
from database.models.payments import PaymentModel, PaymentStatusEnum
from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class _MockEmailSender:
    async def send_activation_email(self, *a, **kw): pass
    async def send_activation_complete_email(self, *a, **kw): pass
    async def send_password_reset_email(self, *a, **kw): pass
    async def send_password_reset_complete_email(self, *a, **kw): pass
    async def send_payment_confirmation_email(self, *a, **kw): pass


def _mock_stripe(order_id=None, user_id=None, session_id="cs_test_123",
                 checkout_url="https://checkout.stripe.com/pay/cs_test_123",
                 amount_total=1500, payment_status="paid",
                 event_type="checkout.session.completed"):
    class _Svc:
        def create_checkout_session(self, order):
            m = MagicMock()
            m.id = session_id
            m.url = checkout_url
            return m

        def retrieve_session(self, sid):
            m = MagicMock()
            m.payment_status = payment_status
            m.metadata = {"order_id": str(order_id), "user_id": str(user_id)}
            m.id = sid
            m.amount_total = amount_total
            return m

        def construct_webhook_event(self, payload, sig_header):
            m = MagicMock()
            m.type = event_type
            obj = MagicMock()
            obj.payment_status = payment_status
            obj.metadata = {"order_id": str(order_id), "user_id": str(user_id)}
            obj.id = session_id
            obj.amount_total = amount_total
            m.data.object = obj
            return m

    return _Svc()


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


async def _get_user_id(email: str) -> int:
    async for db in get_db():
        res = await db.execute(select(UserModel).where(UserModel.email == email))
        return res.scalars().first().id


async def _seed_movie(name="Pay Test Movie", price=15.0) -> int:
    async for db in get_db():
        cert = CertificationModel(name="G")
        db.add(cert)
        await db.flush()
        movie = MovieModel(
            name=name, year=2022, time=100, imdb=7.0,
            votes=100, description="For payment tests", price=price,
            certification_id=cert.id,
        )
        db.add(movie)
        await db.flush()
        await db.commit()
        return movie.id


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _checkout_flow(client, email_suffix, movie_id=None):
    """Register, add movie to cart, create order. Returns (token, order_id, user_id)."""
    if movie_id is None:
        movie_id = await _seed_movie()
    token = await _register_activate_login(client, f"pay_{email_suffix}@test.com")
    user_id = await _get_user_id(f"pay_{email_suffix}@test.com")

    await client.post("/api/v1/cart/items/", json={"movie_id": movie_id}, headers=auth(token))
    order_r = await client.post("/api/v1/orders/", headers=auth(token))
    assert order_r.status_code == 201
    order_id = order_r.json()["id"]
    return token, order_id, user_id


# ---------------------------------------------------------------------------
# 5.1 POST /payments/create-session/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_payment_session(client):
    token, order_id, user_id = await _checkout_flow(client, "session")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(order_id=order_id, user_id=user_id)
    r = await client.post("/api/v1/payments/create-session/",
                          json={"order_id": order_id}, headers=auth(token))

    assert r.status_code == 200
    data = r.json()
    assert data["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_123"
    assert data["session_id"] == "cs_test_123"


@pytest.mark.anyio
async def test_create_session_order_not_found(client):
    token = await _register_activate_login(client, "pay_notfound@test.com")
    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe()
    r = await client.post("/api/v1/payments/create-session/",
                          json={"order_id": 99999}, headers=auth(token))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_create_session_paid_order_returns_400(client):
    token, order_id, user_id = await _checkout_flow(client, "sess400")

    # Mark order as paid directly
    async for db in get_db():
        from database.models.orders import OrderModel, OrderStatusEnum
        res = await db.execute(select(OrderModel).where(OrderModel.id == order_id))
        order = res.scalars().first()
        order.status = OrderStatusEnum.PAID
        await db.commit()
        break

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(order_id=order_id, user_id=user_id)
    r = await client.post("/api/v1/payments/create-session/",
                          json={"order_id": order_id}, headers=auth(token))
    assert r.status_code == 400
    assert "pending" in r.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_session_requires_auth(client):
    r = await client.post("/api/v1/payments/create-session/", json={"order_id": 1})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 5.1 GET /payments/success/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_payment_success_creates_payment(client):
    token, order_id, user_id = await _checkout_flow(client, "succ")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id, amount_total=1500
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    r = await client.get("/api/v1/payments/success/?session_id=cs_test_123")
    assert r.status_code == 200
    assert r.json()["status"] == "paid"

    # Verify PaymentModel was created
    async for db in get_db():
        res = await db.execute(
            select(PaymentModel).where(PaymentModel.order_id == order_id)
        )
        payment = res.scalars().first()
        assert payment is not None
        assert payment.status == PaymentStatusEnum.SUCCESSFUL
        assert payment.external_payment_id == "cs_test_123"
        assert float(payment.amount) == pytest.approx(15.0, abs=0.01)
        break


@pytest.mark.anyio
async def test_payment_success_marks_order_paid(client):
    token, order_id, user_id = await _checkout_flow(client, "succord")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get(f"/api/v1/orders/{order_id}/", headers=auth(token))
    assert r.json()["status"] == "paid"


@pytest.mark.anyio
async def test_payment_success_idempotent(client):
    """Calling success twice doesn't create duplicate payments."""
    token, order_id, user_id = await _checkout_flow(client, "idem")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")
    r2 = await client.get("/api/v1/payments/success/?session_id=cs_test_123")
    assert r2.status_code == 200

    async for db in get_db():
        res = await db.execute(
            select(PaymentModel).where(PaymentModel.external_payment_id == "cs_test_123")
        )
        payments = res.scalars().all()
        assert len(payments) == 1
        break


@pytest.mark.anyio
async def test_payment_success_unpaid_session_returns_400(client):
    token, order_id, user_id = await _checkout_flow(client, "unpaid")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id, payment_status="unpaid"
    )
    r = await client.get("/api/v1/payments/success/?session_id=cs_test_123")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 5.1 GET /payments/cancel/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_payment_cancel_returns_200(client):
    r = await client.get("/api/v1/payments/cancel/?session_id=cs_test_123")
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


# ---------------------------------------------------------------------------
# 5.2 POST /payments/webhook/
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_webhook_checkout_completed_creates_payment(client):
    token, order_id, user_id = await _checkout_flow(client, "wh")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id, event_type="checkout.session.completed"
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    r = await client.post(
        "/api/v1/payments/webhook/",
        content=b'{"type":"checkout.session.completed"}',
        headers={"stripe-signature": "test_sig", "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["received"] is True

    async for db in get_db():
        res = await db.execute(select(PaymentModel).where(PaymentModel.order_id == order_id))
        assert res.scalars().first() is not None
        break


@pytest.mark.anyio
async def test_webhook_invalid_signature_returns_400(client):
    class _BadStripe:
        def construct_webhook_event(self, payload, sig_header):
            raise ValueError("Invalid signature")

    app.dependency_overrides[get_stripe_service] = lambda: _BadStripe()
    r = await client.post(
        "/api/v1/payments/webhook/",
        content=b'{"type":"test"}',
        headers={"stripe-signature": "bad_sig", "content-type": "application/json"},
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_webhook_payment_intent_succeeded_is_noop(client):
    """payment_intent.succeeded events are received but not double-processed."""
    token, order_id, user_id = await _checkout_flow(client, "pi_succ")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id, event_type="payment_intent.succeeded"
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    r = await client.post(
        "/api/v1/payments/webhook/",
        content=b'{"type":"payment_intent.succeeded"}',
        headers={"stripe-signature": "test_sig", "content-type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["received"] is True


# ---------------------------------------------------------------------------
# 5.4 GET /payments/ — list own payments
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_payments_empty(client):
    token = await _register_activate_login(client, "pay_listempty@test.com")
    r = await client.get("/api/v1/payments/", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.anyio
async def test_list_payments_after_payment(client):
    token, order_id, user_id = await _checkout_flow(client, "listpay")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get("/api/v1/payments/", headers=auth(token))
    assert r.status_code == 200
    payments = r.json()
    assert len(payments) == 1
    assert payments[0]["status"] == "successful"
    assert payments[0]["order_id"] == order_id


@pytest.mark.anyio
async def test_list_payments_requires_auth(client):
    r = await client.get("/api/v1/payments/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_payments_isolated_per_user(client):
    movie_id = await _seed_movie()
    token1, order1_id, user1_id = await _checkout_flow(client, "payiso1", movie_id)
    token2 = await _register_activate_login(client, "pay_payiso2@test.com")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order1_id, user_id=user1_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get("/api/v1/payments/", headers=auth(token2))
    assert r.json() == []


# ---------------------------------------------------------------------------
# 5.5 GET /admin/payments/ — moderator sees all payments with filters
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_payments_requires_auth(client):
    r = await client.get("/api/v1/admin/payments/")
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_payments_requires_moderator(client):
    token = await _register_activate_login(client, "pay_admnomod@test.com")
    r = await client.get("/api/v1/admin/payments/", headers=auth(token))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_payments_as_moderator(client):
    token, order_id, user_id = await _checkout_flow(client, "admuser")
    mod_token = await _register_activate_login(client, "pay_admmod@test.com")
    await _make_moderator("pay_admmod@test.com")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get("/api/v1/admin/payments/", headers=auth(mod_token))
    assert r.status_code == 200
    payments = r.json()
    assert isinstance(payments, list)
    assert any(p["order_id"] == order_id for p in payments)


@pytest.mark.anyio
async def test_admin_payments_filter_by_status(client):
    token, order_id, user_id = await _checkout_flow(client, "filtstat")
    mod_token = await _register_activate_login(client, "pay_filtstatmod@test.com")
    await _make_moderator("pay_filtstatmod@test.com")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get("/api/v1/admin/payments/?status=successful", headers=auth(mod_token))
    assert r.status_code == 200
    assert all(p["status"] == "successful" for p in r.json())

    r2 = await client.get("/api/v1/admin/payments/?status=refunded", headers=auth(mod_token))
    assert r2.status_code == 200
    assert r2.json() == []


@pytest.mark.anyio
async def test_admin_payments_filter_by_user_id(client):
    token, order_id, user_id = await _checkout_flow(client, "filtusr")
    mod_token = await _register_activate_login(client, "pay_filtusrmod@test.com")
    await _make_moderator("pay_filtusrmod@test.com")

    app.dependency_overrides[get_stripe_service] = lambda: _mock_stripe(
        order_id=order_id, user_id=user_id
    )
    app.dependency_overrides[get_accounts_email_notificator] = lambda: _MockEmailSender()

    await client.get("/api/v1/payments/success/?session_id=cs_test_123")

    r = await client.get(f"/api/v1/admin/payments/?user_id={user_id}", headers=auth(mod_token))
    assert r.status_code == 200
    assert all(p["user_id"] == user_id for p in r.json())

    r2 = await client.get("/api/v1/admin/payments/?user_id=99999", headers=auth(mod_token))
    assert r2.json() == []


@pytest.mark.anyio
async def test_admin_payments_empty_when_none(client):
    mod_token = await _register_activate_login(client, "pay_admempty@test.com")
    await _make_moderator("pay_admempty@test.com")

    r = await client.get("/api/v1/admin/payments/", headers=auth(mod_token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)
