from datetime import datetime
from typing import List

from pydantic import BaseModel


class PaymentItemSchema(BaseModel):
    id: int
    order_item_id: int
    price_at_payment: float

    model_config = {"from_attributes": True}


class PaymentSchema(BaseModel):
    id: int
    user_id: int
    order_id: int
    status: str
    amount: float
    created_at: datetime
    external_payment_id: str
    items: List[PaymentItemSchema] = []

    model_config = {"from_attributes": True}


class CreatePaymentSessionSchema(BaseModel):
    order_id: int


class CreateSessionResponseSchema(BaseModel):
    checkout_url: str
    session_id: str
