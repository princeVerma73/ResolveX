"""Shared Agent State definition for ResolveX LangGraph multi-agent architecture.

Step 6 — Phase 1: Agent State & Structured LLM Intent Router.

WHAT:
    Defines the universal `AgentState` Pydantic model representing multi-turn conversational state,
    routing decisions, entity buffers, tool execution outputs, RAG context, and resolution payloads.

WHY:
    - Provides a single, strongly typed state container propagated across all LangGraph nodes.
    - Prevents data loss during multi-turn handoffs between specialist sub-agents.
    - Ensures clear separation of concerns between conversational history and intermediate execution results.

HOW:
    - Encapsulates `session_id`, `customer_id`, `messages`, `current_query`, `route_decision`,
      `retrieved_chunks`, `db_lookup_results`, `action_results`, `final_response`, and routing flags.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import BaseModel, Field

from Backend.rag.reranking import RankedChunk


class AgentState(BaseModel):
    """Universal state schema for ResolveX LangGraph multi-agent workflows.

    Attributes:
        session_id: Unique chat session identifier.
        customer_id: Authenticated or extracted customer ID (if known).
        messages: Chronological conversation message turns.
        current_query: The active customer query being processed in this turn.
        route_decision: Structured classification output from IntentRouter.
        retrieved_chunks: Grounded policy chunks retrieved from Step 5 RAG pipeline.
        db_lookup_results: Structured data retrieved from database services (orders, payments).
        action_results: Mutation execution results (e.g. order cancellation status).
        final_response: Synthesized customer-facing response text.
        is_escalated: True if conversation was escalated to a human support agent.
        clarification_needed: True if additional entity or intent clarification is required.
    """

    session_id: str = Field(..., description="Unique chat session ID")
    customer_id: str | None = Field(default=None, description="Customer identifier if known")
    messages: list[dict[str, Any]] = Field(
        default_factory=list, description="Conversational message history turns"
    )
    current_query: str = Field(..., description="Active user query for this execution turn")
    route_decision: Any | None = Field(
        default=None, description="Structured RouteDecision object from IntentRouter"
    )
    retrieved_chunks: list[RankedChunk] = Field(
        default_factory=list, description="Top ranked grounded policy passages"
    )
    db_lookup_results: dict[str, Any] = Field(
        default_factory=dict, description="Operational database lookup outputs"
    )
    action_results: dict[str, Any] = Field(
        default_factory=dict, description="Transactional tool mutation outputs"
    )
    final_response: str | None = Field(
        default=None, description="Final synthesized assistant resolution"
    )
    is_escalated: bool = Field(
        default=False, description="Flag indicating human specialist escalation"
    )
    clarification_needed: bool = Field(
        default=False, description="Flag indicating missing parameter clarification"
    )
