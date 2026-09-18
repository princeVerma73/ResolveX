"""Pydantic domain schemas for Customers."""

from datetime import datetime
from pydantic import EmailStr, Field
from Backend.schemas.common import CustomerTier, ResolveXBaseSchema


class CustomerBase(ResolveXBaseSchema):
    """Base customer fields."""
    full_name: str = Field(..., min_length=1, max_length=255, description="Customer's full legal or display name")
    email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
        description="Unique customer email address",
    )
    phone: str | None = Field(default=None, max_length=50, description="Customer contact phone number")
    tier: CustomerTier = Field(default=CustomerTier.STANDARD, description="Customer priority membership tier")


class CustomerCreate(CustomerBase):
    """Payload schema for registering or inserting a new customer."""
    customer_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional customer ID. Auto-generated if omitted.",
    )


class CustomerUpdate(ResolveXBaseSchema):
    """Payload schema for partially updating an existing customer."""
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$",
    )
    phone: str | None = Field(default=None, max_length=50)
    tier: CustomerTier | None = Field(default=None)


class CustomerResponse(CustomerBase):
    """Full customer record returned from database operations."""
    customer_id: str = Field(..., max_length=64, description="Unique customer identifier")
    created_at: datetime = Field(..., description="Timestamp when customer profile was created")
    updated_at: datetime = Field(..., description="Timestamp when customer profile was last updated")
