import stripe

from database.models.orders import OrderModel


class StripeService:
    def __init__(self, api_key: str, webhook_secret: str, success_url: str, cancel_url: str):
        stripe.api_key = api_key
        self._webhook_secret = webhook_secret
        self._success_url = success_url
        self._cancel_url = cancel_url

    def create_checkout_session(self, order: OrderModel):
        line_items = [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item.movie.name},
                    "unit_amount": int(float(item.price_at_order) * 100),
                },
                "quantity": 1,
            }
            for item in order.items
        ]
        return stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=self._success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=self._cancel_url + "?session_id={CHECKOUT_SESSION_ID}",
            metadata={"order_id": str(order.id), "user_id": str(order.user_id)},
        )

    def retrieve_session(self, session_id: str):
        return stripe.checkout.Session.retrieve(session_id)

    def construct_webhook_event(self, payload: bytes, sig_header: str):
        return stripe.Webhook.construct_event(payload, sig_header, self._webhook_secret)
