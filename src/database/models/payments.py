import enum
from datetime import datetime
from decimal import Decimal
from typing import List

from sqlalchemy import Integer, ForeignKey, DateTime, Numeric, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base


class PaymentStatusEnum(str, enum.Enum):
    SUCCESSFUL = "successful"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[PaymentStatusEnum] = mapped_column(
        Enum(PaymentStatusEnum), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    external_payment_id: Mapped[str] = mapped_column(String(255), nullable=False)

    user = relationship("UserModel", foreign_keys=[user_id])
    order = relationship("OrderModel", foreign_keys=[order_id])
    items: Mapped[List["PaymentItemModel"]] = relationship(
        "PaymentItemModel", back_populates="payment", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Payment(id={self.id}, order={self.order_id}, status={self.status})>"


class PaymentItemModel(Base):
    __tablename__ = "payment_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), nullable=False
    )
    price_at_payment: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    payment: Mapped["PaymentModel"] = relationship("PaymentModel", back_populates="items")
    order_item = relationship("OrderItemModel", foreign_keys=[order_item_id])

    def __repr__(self):
        return f"<PaymentItem(payment={self.payment_id}, order_item={self.order_item_id})>"
