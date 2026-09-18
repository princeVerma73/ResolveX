"""Pydantic domain schemas for Chat Sessions and Messages."""

from datetime import datetime
from typing import Any
from pydantic import Field
from Backend.schemas.common import ResolveXBaseSchema, SenderType, SessionStatus


# =============================================================================
# Messages
# =============================================================================

class MessageBase(ResolveXBaseSchema):
    """Base schema for conversational message turns."""
    session_id: str = Field(..., max_length=64, description="Target chat session ID")
    sender_type: SenderType = Field(..., description="Message author (USER, AGENT, SYSTEM, TOOL)")
    content: str = Field(..., min_length=1, description="Message text or tool response string")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom turn metadata or citations")


class MessageCreate(ResolveXBaseSchema):
    """Payload schema for inserting a new message into a session."""
    message_id: str | None = Field(default=None, max_length=64, description="Optional custom message ID")
    session_id: str = Field(..., max_length=64, description="Target chat session ID")
    sender_type: SenderType = Field(..., description="Message author")
    content: str = Field(..., min_length=1, description="Message body")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Metadata dictionary")


class MessageResponse(MessageBase):
    """Full message turn record returned from database operations."""
    message_id: str = Field(..., max_length=64, description="Unique message identifier")
    created_at: datetime = Field(..., description="Timestamp when message was stored")


# =============================================================================
# Chat Sessions
# =============================================================================

class ChatSessionBase(ResolveXBaseSchema):
    """Base schema for conversational sessions."""
    customer_id: str | None = Field(default=None, max_length=64, description="Associated customer ID")
    channel: str = Field(default="WEB_CHAT", max_length=30, description="Communication channel")
    status: SessionStatus = Field(default=SessionStatus.ACTIVE, description="Session state")
    context_entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted memory entities (e.g. active_order_id, topic, intent)",
    )
    conversation_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Compact conversation turn summaries or raw history list",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary session metadata (browser, IP, device, sentiment)",
    )


class ChatSessionCreate(ChatSessionBase):
    """Payload schema for creating a new chat session."""
    session_id: str | None = Field(default=None, max_length=64, description="Optional custom session ID")


class ChatSessionUpdate(ResolveXBaseSchema):
    """Payload schema for updating session context, history, or status."""
    customer_id: str | None = Field(default=None, max_length=64)
    channel: str | None = Field(default=None, max_length=30)
    status: SessionStatus | None = Field(default=None)
    context_entities: dict[str, Any] | None = Field(default=None)
    conversation_history: list[dict[str, Any]] | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class ChatSessionResponse(ChatSessionBase):
    """Full chat session record returned from database operations."""
    session_id: str = Field(..., max_length=64, description="Unique chat session identifier")
    created_at: datetime = Field(..., description="Timestamp when session was opened")
    updated_at: datetime = Field(..., description="Timestamp when session was last updated")


class ChatSessionWithMessagesResponse(ChatSessionResponse):
    """Composite session record including chronological list of message turns."""
    messages: list[MessageResponse] = Field(default_factory=list, description="Session messages")
