"""Pydantic domain schemas for Orders and Order Items."""

from datetime import datetime
from decimal import Decimal
from pydantic import Field
from Backend.schemas.common import OrderStatus, ResolveXBaseSchema


# =============================================================================
# Order Items
# =============================================================================

class OrderItemBase(ResolveXBaseSchema):
    """Base schema for order line items."""
    product_name: str = Field(..., min_length=1, max_length=255, description="Name or title of ordered product")
    quantity: int = Field(default=1, gt=0, description="Quantity ordered (must be >= 1)")
    unit_price: Decimal = Field(..., ge=0, decimal_places=2, description="Price per unit")


class OrderItemCreate(OrderItemBase):
    """Payload schema for creating an order line item."""
    item_id: str | None = Field(default=None, max_length=64, description="Optional custom item ID")
    order_id: str | None = Field(default=None, max_length=64, description="Order ID to associate item with")


class OrderItemResponse(OrderItemBase):
    """Full order item record returned from database operations."""
    item_id: str = Field(..., max_length=64, description="Unique item identifier")
    order_id: str = Field(..., max_length=64, description="Referenced order identifier")
    created_at: datetime = Field(..., description="Timestamp when line item was created")


# =============================================================================
# Orders
# =============================================================================

class OrderBase(ResolveXBaseSchema):
    """Base schema for customer orders."""
    customer_id: str = Field(..., max_length=64, description="Customer ID placing the order")
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Current fulfillment status")
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2, description="Total order amount")
    currency: str = Field(default="USD", max_length=10, description="Three-letter or standard currency code")
    shipping_address: str | None = Field(default=None, description="Physical shipping destination address")
    tracking_number: str | None = Field(default=None, max_length=100, description="Carrier shipment tracking number")
    estimated_delivery: datetime | None = Field(default=None, description="Estimated delivery timestamp")


class OrderCreate(OrderBase):
    """Payload schema for creating a new customer order."""
    order_id: str | None = Field(default=None, max_length=64, description="Optional custom order ID")
    items: list[OrderItemCreate] = Field(default_factory=list, description="Optional initial line items")


class OrderUpdate(ResolveXBaseSchema):
    """Payload schema for updating an existing order's state or delivery tracking."""
    status: OrderStatus | None = Field(default=None)
    total_amount: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    currency: str | None = Field(default=None, max_length=10)
    shipping_address: str | None = Field(default=None)
    tracking_number: str | None = Field(default=None, max_length=100)
    estimated_delivery: datetime | None = Field(default=None)


class OrderResponse(OrderBase):
    """Standard order record returned from database operations."""
    order_id: str = Field(..., max_length=64, description="Unique order identifier")
    created_at: datetime = Field(..., description="Timestamp when order was placed")
    updated_at: datetime = Field(..., description="Timestamp when order was last modified")


class OrderWithDetailsResponse(OrderResponse):
    """Composite order record including nested line items and associated payment records."""
    items: list[OrderItemResponse] = Field(default_factory=list, description="Ordered line items")
    payments: list[dict] = Field(default_factory=list, description="Associated payment records")
