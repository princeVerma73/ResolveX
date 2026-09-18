"""Pydantic domain schemas for Support Tickets."""

from datetime import datetime
from pydantic import Field
from Backend.schemas.common import (
    ResolveXBaseSchema,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)


class TicketBase(ResolveXBaseSchema):
    """Base schema for support tickets."""
    customer_id: str | None = Field(default=None, max_length=64, description="Associated customer ID")
    session_id: str | None = Field(default=None, max_length=64, description="Originating chat session ID")
    order_id: str | None = Field(default=None, max_length=64, description="Referenced order ID if applicable")
    category: TicketCategory = Field(default=TicketCategory.GENERAL, description="Ticket classification")
    priority: TicketPriority = Field(default=TicketPriority.MEDIUM, description="Ticket urgency level")
    status: TicketStatus = Field(default=TicketStatus.OPEN, description="Current workflow state")
    subject: str = Field(..., min_length=1, max_length=255, description="Brief summary of customer issue")
    description: str = Field(..., min_length=1, description="Detailed problem statement or transcript")
    assigned_agent: str | None = Field(default=None, max_length=100, description="Name or ID of assigned human agent")
    resolution_notes: str | None = Field(default=None, description="Resolution outcome or agent remarks")


class TicketCreate(TicketBase):
    """Payload schema for filing a new support ticket."""
    ticket_id: str | None = Field(default=None, max_length=64, description="Optional custom ticket ID")


class TicketUpdate(ResolveXBaseSchema):
    """Payload schema for modifying ticket status, assignments, or notes."""
    category: TicketCategory | None = Field(default=None)
    priority: TicketPriority | None = Field(default=None)
    status: TicketStatus | None = Field(default=None)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    assigned_agent: str | None = Field(default=None, max_length=100)
    resolution_notes: str | None = Field(default=None)


class TicketResponse(TicketBase):
    """Full ticket record returned from database operations."""
    ticket_id: str = Field(..., max_length=64, description="Unique support ticket identifier")
    created_at: datetime = Field(..., description="Timestamp when ticket was created")
    updated_at: datetime = Field(..., description="Timestamp when ticket was last updated")
