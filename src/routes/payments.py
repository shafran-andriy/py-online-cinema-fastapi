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


@router.post("/create-session/", response_model=CreateSessionResponseSchema)
async def create_payment_session(
    body: CreatePaymentSessionSchema,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
    stripe_svc: StripeService = Depends(get_stripe_service),
):
    order = await _load_order_with_items(db, body.order_id, user_id=current_user.id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.status != OrderStatusEnum.PENDING:
        raise HTTPException(status_code=400, detail="Order is not in pending status.")

    session = stripe_svc.create_checkout_session(order)
    return CreateSessionResponseSchema(checkout_url=session.url, session_id=session.id)


@router.get("/success/")
async def payment_success(
    session_id: str = Query(...),
    db=Depends(get_db),
    stripe_svc: StripeService = Depends(get_stripe_service),
    email_svc: EmailSenderInterface = Depends(get_accounts_email_notificator),
):
    session = stripe_svc.retrieve_session(session_id)
    if session.payment_status != "paid":
        raise HTTPException(status_code=400, detail="Payment not completed.")
    await _process_paid_session(session, db, email_svc)
    return {"status": "paid", "session_id": session_id}


@router.get("/cancel/")
async def payment_cancel(session_id: str = Query(...)):
    return {"status": "canceled", "session_id": session_id}


@router.post("/webhook/")
async def stripe_webhook(
    request: Request,
    db=Depends(get_db),
    stripe_svc: StripeService = Depends(get_stripe_service),
    email_svc: EmailSenderInterface = Depends(get_accounts_email_notificator),
):
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


@router.get("/", response_model=list[PaymentSchema])
async def list_payments(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
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
