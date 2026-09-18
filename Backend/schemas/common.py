"""Common enums, constants, and base model configurations for ResolveX domain schemas."""

from enum import Enum
from pydantic import BaseModel, ConfigDict


class CustomerTier(str, Enum):
    """Customer membership and priority tiers."""
    STANDARD = "STANDARD"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class OrderStatus(str, Enum):
    """Order fulfillment and lifecycle statuses."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class PaymentStatus(str, Enum):
    """Financial transaction statuses."""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    """Supported customer payment methods."""
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    PAYPAL = "PAYPAL"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    WALLET = "WALLET"


class SessionStatus(str, Enum):
    """Chat session lifecycle states."""
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SenderType(str, Enum):
    """Origin of a chat message in the conversation stream."""
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class TicketCategory(str, Enum):
    """Support ticket categorization for routing and resolution."""
    ORDER = "ORDER"
    BILLING = "BILLING"
    TECHNICAL = "TECHNICAL"
    POLICY = "POLICY"
    GENERAL = "GENERAL"
    REFUND = "REFUND"
    SHIPPING = "SHIPPING"


class TicketPriority(str, Enum):
    """Support ticket severity and priority levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class TicketStatus(str, Enum):
    """Support ticket workflow states."""
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ResolveXBaseSchema(BaseModel):
    """Base schema for all ResolveX Pydantic models."""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        str_strip_whitespace=True,
    )
