"""Pydantic domain schemas for Payments and Transactions."""

from datetime import datetime
from decimal import Decimal
from pydantic import Field
from Backend.schemas.common import PaymentMethod, PaymentStatus, ResolveXBaseSchema


class PaymentBase(ResolveXBaseSchema):
    """Base schema for payments."""
    order_id: str = Field(..., max_length=64, description="Referenced order identifier")
    amount: Decimal = Field(..., ge=0, decimal_places=2, description="Payment transaction amount")
    status: PaymentStatus = Field(default=PaymentStatus.PENDING, description="Transaction status")
    payment_method: PaymentMethod | None = Field(default=None, description="Payment method used")
    transaction_ref: str | None = Field(default=None, max_length=100, description="External gateway reference or ID")


class PaymentCreate(PaymentBase):
    """Payload schema for recording a payment transaction."""
    payment_id: str | None = Field(default=None, max_length=64, description="Optional custom payment ID")


class PaymentUpdate(ResolveXBaseSchema):
    """Payload schema for updating payment status or gateway references."""
    status: PaymentStatus | None = Field(default=None)
    payment_method: PaymentMethod | None = Field(default=None)
    transaction_ref: str | None = Field(default=None, max_length=100)


class PaymentResponse(PaymentBase):
    """Full payment record returned from database operations."""
    payment_id: str = Field(..., max_length=64, description="Unique payment transaction identifier")
    created_at: datetime = Field(..., description="Timestamp when payment record was created")
    updated_at: datetime = Field(..., description="Timestamp when payment record was last modified")
