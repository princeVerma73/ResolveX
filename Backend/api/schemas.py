"""Pydantic API request and response schemas for ResolveX REST and WebSocket endpoints.

Step 7: API Layer & WebSocket Chat.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Payload for incoming customer chat messages."""

    query: str = Field(
        ...,
        min_length=1,
        description="The customer's natural language inquiry or command",
        examples=["Where is my order ORD-8832?"],
    )
    session_id: str | None = Field(
        default=None,
        description="Existing session identifier. A new session ID will be generated if not provided.",
        examples=["SES-48A1B90D2411"],
    )
    customer_id: str | None = Field(
        default=None,
        description="Optional customer ID for authenticated users",
        examples=["CUST-001"],
    )
    history: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional list of recent conversational turns `[{'role': 'user', 'content': '...'}]`",
    )


class ChatResponse(BaseModel):
    """Structured response container returned to the customer client."""

    session_id: str = Field(..., description="Active session identifier")
    customer_id: str | None = Field(default=None, description="Associated customer ID")
    query: str = Field(..., description="Processed user query")
    response: str = Field(..., description="Synthesized agent response or resolution")
    intent: str | None = Field(default=None, description="Classified intent taxonomy")
    confidence: float | None = Field(default=None, description="Intent classification confidence")
    citations: list[str] = Field(
        default_factory=list,
        description="Document chunk IDs or passage references supporting the response",
    )
    is_escalated: bool = Field(
        default=False,
        description="Whether this query has been routed to a human support specialist",
    )
    clarification_needed: bool = Field(
        default=False,
        description="Whether the agent requires additional user confirmation or parameters",
    )
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain entities extracted by the Intent Router (order_id, email, etc.)",
    )
    action_results: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool execution results, diagnostic reports, or mutation receipts",
    )


class SessionHistoryResponse(BaseModel):
    """Conversation history payload for a specific chat session."""

    session_id: str = Field(..., description="Target session identifier")
    customer_id: str | None = Field(default=None, description="Associated customer ID")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Chronological message history turns",
    )
    status: str = Field(default="ACTIVE", description="Session lifecycle status")
    created_at: str | None = Field(default=None, description="Creation timestamp")
    updated_at: str | None = Field(default=None, description="Last updated timestamp")


class HealthResponse(BaseModel):
    """System health check diagnostics payload."""

    status: str = Field(default="ok", description="Overall application status")
    database: str = Field(default="reachable", description="PostgreSQL database reachability status")
    agent_orchestrator: str = Field(default="ready", description="LangGraph agent orchestrator status")
    version: str = Field(default="1.0.0", description="API version")


class VisitorCountResponse(BaseModel):
    """Global live visitor counter payload."""

    total_visitors: int = Field(..., description="Cumulative count of platform visitors")
