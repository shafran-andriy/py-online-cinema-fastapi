from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config.dependencies import get_stripe_service, get_accounts_email_notificator
from database import get_db, UserModel
from database.models.orders import OrderModel, OrderItemModel, OrderStatusEnum
from database.models.payments import PaymentModel, PaymentItemModel, PaymentStatusEnum
from notifications.interfaces import EmailSenderInterface
from schemas.payments import (
    PaymentSchema,
    CreatePaymentSessionSchema,
    CreateSessionResponseSchema,
)
from security.deps import get_current_user
from services.payments import StripeService

router = APIRouter()


async def _load_order_with_items(db, order_id: int, user_id: int = None) -> OrderModel | None:
    stmt = (
        select(OrderModel)
        .options(
            selectinload(OrderModel.items)
            .selectinload(OrderItemModel.movie)
        )
        .where(OrderModel.id == order_id)
        .execution_options(populate_existing=True)
    )
    if user_id is not None:
        stmt = stmt.where(OrderModel.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _process_paid_session(session_obj, db, email_svc: EmailSenderInterface) -> None:
    """Idempotent: create PaymentModel, update order to PAID, send confirmation email."""
    order_id = int(session_obj.metadata["order_id"])
    user_id = int(session_obj.metadata["user_id"])
    external_id = str(session_obj.id)

    res = await db.execute(
        select(PaymentModel).where(PaymentModel.external_payment_id == external_id)
    )
    if res.scalars().first():
        return

    order = await _load_order_with_items(db, order_id)
    if not order or order.status == OrderStatusEnum.PAID:
        return

    amount = Decimal(str(session_obj.amount_total)) / 100

    payment = PaymentModel(
        user_id=user_id,
        order_id=order_id,
        status=PaymentStatusEnum.SUCCESSFUL,
        amount=amount,
        external_payment_id=external_id,
    )
    db.add(payment)
    await db.flush()

    for item in order.items:
        db.add(PaymentItemModel(
            payment_id=payment.id,
            order_item_id=item.id,
            price_at_payment=item.price_at_order,
        ))

    order.status = OrderStatusEnum.PAID
    await db.commit()

    user_res = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user = user_res.scalars().first()
    if user:
        try:
            await email_svc.send_payment_confirmation_email(
                email=user.email,
                order_id=order_id,
                amount=float(amount),
            )
        except Exception:
            pass


@router.post(
    "/create-session/",
    response_model=CreateSessionResponseSchema,
    summary="Create Stripe Checkout session",
    description="""
Creates a Stripe Checkout session for a pending order and returns the payment URL.

**Request body:**
```json
{
  "order_id": 12
}
```

**Validation:**
- The order must exist and belong to the current user — `404` if not.
- The order must be in `pending` status — `400` if already paid or canceled.

**Response:**
```json
{
  "checkout_url": "https://checkout.stripe.com/pay/cs_test_...",
  "session_id": "cs_test_..."
}
```

Redirect the user to `checkout_url` to complete payment on Stripe's hosted page.
After successful payment Stripe redirects to `/api/v1/payments/success/?session_id=...`.

**Auth:** Bearer token required.
    """,
)
async def create_payment_session(
    body: CreatePaymentSessionSchema,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
    stripe_svc: StripeService = Depends(get_stripe_service),
):
    """
    Create a Stripe Checkout session for the specified pending order.

    Args:
        body: CreatePaymentSessionSchema with order_id (int).

    Raises:
        404: Order not found or does not belong to the current user.
        400: Order is not in PENDING status.

    Returns:
        CreateSessionResponseSchema: checkout_url and session_id from Stripe.
    """
    order = await _load_order_with_items(db, body.order_id, user_id=current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail="Order is not in pending status.")

    session = stripe_svc.create_checkout_session(order)
    return CreateSessionResponseSchema(checkout_url=session.url, session_id=session.id)


@router.get(
    "/success/",
    summary="Stripe success callback",
    description="""
Handles the redirect from Stripe after a successful payment.

**Query parameter:**
- `session_id` (str) — Stripe Checkout session ID (provided automatically by Stripe redirect).

**On success:**
- Verifies the session payment status is `paid`.
- Creates a `PaymentModel` record (idempotent — safe to call multiple times).
- Updates the associated order status to `PAID`.
- Sends a payment confirmation email to the user.

**Note:** This endpoint is called by Stripe redirect, not directly by the user.
Typically opened in the browser after the user completes payment on Stripe.

Returns `400` if payment was not completed.
    """,
)
async def payment_success(
    session_id: str = Query(..., description="Stripe Checkout session ID"),
    db=Depends(get_db),
    stripe_svc: StripeService = Depends(get_stripe_service),
    email_svc: EmailSenderInterface = Depends(get_accounts_email_notificator),
):
    """
    Handle Stripe success redirect and finalize the payment.

    Retrieves the Stripe session, verifies payment status, creates a PaymentModel,
    updates the order to PAID, and sends a confirmation email. Operation is idempotent.

    Args:
        session_id: Stripe Checkout session ID from query string.

    Raises:
        400: Stripe session payment_status is not 'paid'.

    Returns:
        dict: {"status": "paid", "session_id": session_id}
    """
    session = stripe_svc.retrieve_session(session_id)
    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed.")
    await _process_paid_session(session, db, email_svc)
    return {"status": "paid", "session_id": session_id}


@router.get(
    "/cancel/",
    summary="Stripe cancel callback",
    description="""
Handles the redirect from Stripe when the user cancels the payment.

**Query parameter:**
- `session_id` (str) — Stripe Checkout session ID.

The order remains in `pending` status and can be paid later by creating a new session.

**Note:** This endpoint is called by Stripe redirect when the user clicks "Back" or "Cancel"
on the Stripe Checkout page.
    """,
)
async def payment_cancel(
    session_id: str = Query(..., description="Stripe Checkout session ID"),
):
    """
    Handle Stripe cancel redirect when the user abandons the payment.

    The order is NOT canceled — it remains PENDING and can be retried.

    Args:
        session_id: Stripe Checkout session ID from query string.

    Returns:
        dict: {"status": "canceled", "session_id": session_id}
    """
    return {"status": "canceled", "session_id": session_id}


@router.post(
    "/webhook/",
    summary="Stripe webhook handler",
    description="""
Receives and processes Stripe webhook events. Called automatically by Stripe — **not by clients**.

**Handled events:**
- `checkout.session.completed` with `payment_status = paid`:
  Creates payment record, marks order as PAID, sends confirmation email.
- `payment_intent.succeeded`:
  Acknowledged but not processed separately (handled via session event above).

**Security:** Stripe signature in `stripe-signature` header is verified using `STRIPE_WEBHOOK_SECRET`.
Returns `400` if the signature is invalid.

**Setup:** Configure the webhook URL in Stripe Dashboard:
`https://your-domain.com/api/v1/payments/webhook/`

**Auth:** No user auth — authenticated via Stripe signature.
    """,
)
async def stripe_webhook(
    request: Request,
    db=Depends(get_db),
    stripe_svc: StripeService = Depends(get_stripe_service),
    email_svc: EmailSenderInterface = Depends(get_accounts_email_notificator),
):
    """
    Process incoming Stripe webhook events.

    Verifies the Stripe-Signature header, then handles:
    - checkout.session.completed → finalize payment and mark order as PAID.
    - payment_intent.succeeded → no-op (metadata only on session events).

    Raises:
        400: Invalid webhook signature.

    Returns:
        dict: {"received": True} on successful processing.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe_svc.construct_webhook_event(payload, sig_header)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    if event.type == "checkout.session.completed":
        session_obj = event.data.object
        if getattr(session_obj, "payment_status", None) == "paid":
            await _process_paid_session(session_obj, db, email_svc)
    elif event.type == "payment_intent.succeeded":
        # payment_intent events fire alongside checkout.session.completed in checkout flows.
        # The session event carries order metadata; the intent event does not — handled above.
        pass

    return {"received": True}


@router.get(
    "/",
    response_model=list[PaymentSchema],
    summary="List my payments",
    description="""
Returns all successful payments made by the currently authenticated user, sorted by date (newest first).

Each payment record includes:
- `id` — payment identifier
- `order_id` — associated order
- `amount` — total amount charged (in currency units, e.g. USD)
- `status` — `SUCCESSFUL` | `CANCELED` | `REFUNDED`
- `external_payment_id` — Stripe session ID for reference
- `items` — individual items with `price_at_payment` for each movie

**Auth:** Bearer token required.
    """,
)
async def list_payments(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Retrieve all payment records for the authenticated user.

    Sorted by created_at descending (newest first).
    Each payment includes its items with the price locked at time of payment.

    Returns:
        list[PaymentSchema]: All payments belonging to the current user.
    """
    stmt = (
        select(PaymentModel)
        .options(selectinload(PaymentModel.items))
        .where(PaymentModel.user_id == current_user.id)
        .order_by(PaymentModel.created_at.desc())
        .execution_options(populate_existing=True)
    )
    result = await db.execute(stmt)
    payments = result.scalars().all()
    return [PaymentSchema.model_validate(p) for p in payments]
