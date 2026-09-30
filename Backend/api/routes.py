"""FastAPI route handlers for ResolveX customer chat and session management.

Step 7: API Layer & WebSocket Chat.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import APIRouter, Depends, HTTPException, Request, status

from Backend.agent.graph import SupportAgentOrchestrator
from Backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistoryResponse,
    VisitorCountResponse,
)
from Backend.core.exceptions import ResourceNotFoundError
from Backend.db.supabase_client import verify_connection
from Backend.services.chat_service import ChatService
from Backend.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat & Support"])


def get_orchestrator(request: Request) -> SupportAgentOrchestrator:
    """Dependency provider for SupportAgentOrchestrator instance."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        orchestrator = SupportAgentOrchestrator()
    return orchestrator


def get_chat_service() -> ChatService:
    """Dependency provider for ChatService."""
    return ChatService()


# -----------------------------------------------------------------------------
# 1. Health Diagnostics
# -----------------------------------------------------------------------------

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System Health Diagnostics",
    description="Probes database connectivity and agent orchestrator availability.",
)
async def health_check(request: Request) -> HealthResponse:
    """Probes system components and returns operational status."""
    db_status = "reachable"
    try:
        is_connected = verify_connection()
        if not is_connected:
            db_status = "degraded"
    except Exception as exc:
        logger.warning("Database health check probe failed: %s", exc)
        db_status = "unreachable"

    orchestrator = getattr(request.app.state, "orchestrator", None)
    orch_status = "ready" if orchestrator is not None else "lazy_init"

    overall_status = "ok" if db_status in ("reachable", "degraded") else "degraded"

    return HealthResponse(
        status=overall_status,
        database=db_status,
        agent_orchestrator=orch_status,
        version="1.0.0",
    )


# -----------------------------------------------------------------------------
# 2. REST Chat Endpoint
# -----------------------------------------------------------------------------

@router.post(
    "/api/chat",
    response_model=ChatResponse,
    summary="Process Customer Chat Message",
    description="Invokes the LangGraph multi-agent orchestrator to classify, process, and resolve inquiries.",
)
async def chat_endpoint(
    payload: ChatRequest,
    orchestrator: SupportAgentOrchestrator = Depends(get_orchestrator),
    chat_svc: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """Processes a user message turn through the LangGraph supervisor workflow."""
    clean_query = payload.query.strip()
    if not clean_query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query string cannot be empty.",
        )

    session_id = payload.session_id or f"SES-{uuid.uuid4().hex[:12].upper()}"

    try:
        # 1. High-throughput Redis Cache check (sub-10ms lookup)
        cached = await redis_cache.get_cached_response(clean_query)
        if cached:
            logger.info("Redis cache HIT for query: '%s'", clean_query[:50])
            # Best-effort message logging to ChatService (non-blocking)
            try:
                from Backend.schemas.chat import MessageCreate
                from Backend.schemas.common import SenderType

                chat_svc.add_message(
                    MessageCreate(
                        session_id=session_id,
                        sender_type=SenderType.USER,
                        content=clean_query,
                    )
                )
                if cached.get("response"):
                    chat_svc.add_message(
                        MessageCreate(
                            session_id=session_id,
                            sender_type=SenderType.AGENT,
                            content=cached["response"],
                        )
                    )
            except Exception as exc:
                logger.debug("Chat session message persistence skipped: %s", exc)

            return ChatResponse(
                session_id=session_id,
                customer_id=payload.customer_id,
                query=clean_query,
                response=cached.get("response", ""),
                intent=cached.get("intent", "POLICY_INQUIRY"),
                confidence=cached.get("confidence", 0.98),
                citations=cached.get("citations", []),
                is_escalated=False,
                clarification_needed=False,
                entities=cached.get("entities", {}),
                action_results=cached.get("action_results", {}),
                source="REDIS_CACHE",
            )

        # 2. Cache MISS: Execute LangGraph Multi-Agent Pipeline
        state = await orchestrator.arun(
            query=clean_query,
            session_id=session_id,
            customer_id=payload.customer_id,
            history=payload.history,
        )

        # Extract citations from retrieved grounded chunks
        citations = []
        if state.retrieved_chunks:
            for chunk in state.retrieved_chunks:
                cid = getattr(chunk, "chunk_id", None)
                if cid and cid not in citations:
                    citations.append(cid)

        # Extract structured entities
        entities_dict = {}
        if state.route_decision and hasattr(state.route_decision, "entities"):
            entities_obj = state.route_decision.entities
            if hasattr(entities_obj, "model_dump"):
                entities_dict = {k: v for k, v in entities_obj.model_dump().items() if v is not None}
            elif isinstance(entities_obj, dict):
                entities_dict = {k: v for k, v in entities_obj.items() if v is not None}

        # Extract intent and confidence
        intent_val = (
            state.route_decision.intent.value
            if state.route_decision and hasattr(state.route_decision.intent, "value")
            else str(state.route_decision.intent) if state.route_decision and state.route_decision.intent
            else None
        )
        confidence_val = (
            state.route_decision.confidence
            if state.route_decision and hasattr(state.route_decision, "confidence")
            else None
        )

        # 3. Cache population on grounded policy inquiries only
        if redis_cache.should_cache(
            intent=intent_val,
            is_escalated=state.is_escalated,
            clarification_needed=state.clarification_needed,
        ):
            cache_payload = {
                "response": state.final_response,
                "intent": intent_val,
                "confidence": confidence_val,
                "citations": citations,
                "entities": entities_dict,
                "action_results": state.action_results,
            }
            await redis_cache.set_cached_response(clean_query, cache_payload)

        # Best-effort message logging to ChatService (non-blocking)
        try:
            from Backend.schemas.chat import MessageCreate
            from Backend.schemas.common import SenderType

            chat_svc.add_message(
                MessageCreate(
                    session_id=session_id,
                    sender_type=SenderType.USER,
                    content=clean_query,
                )
            )
            if state.final_response:
                chat_svc.add_message(
                    MessageCreate(
                        session_id=session_id,
                        sender_type=SenderType.AGENT,
                        content=state.final_response,
                    )
                )
        except Exception as exc:
            logger.debug("Chat session message persistence skipped: %s", exc)

        return ChatResponse(
            session_id=session_id,
            customer_id=state.customer_id or payload.customer_id,
            query=clean_query,
            response=state.final_response or "Your inquiry has been received.",
            intent=intent_val,
            confidence=confidence_val,
            citations=citations,
            is_escalated=state.is_escalated,
            clarification_needed=state.clarification_needed,
            entities=entities_dict,
            action_results=state.action_results,
            source="ORCHESTRATOR",
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error executing chat_endpoint: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing your request: {exc}",
        )


# -----------------------------------------------------------------------------
# 3. Session History Endpoint
# -----------------------------------------------------------------------------

@router.get(
    "/api/sessions/{session_id}",
    response_model=SessionHistoryResponse,
    summary="Retrieve Chat Session Message Thread",
    description="Fetches the full conversation transcript for a given session identifier.",
)
async def get_session_history(
    session_id: str,
    chat_svc: ChatService = Depends(get_chat_service),
) -> SessionHistoryResponse:
    """Retrieves stored conversation messages for a session."""
    clean_id = session_id.strip()
    if not clean_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session ID must not be empty.",
        )

    try:
        session_data = chat_svc.get_session_with_messages(clean_id)
        messages_list = [msg.model_dump(mode="json") for msg in session_data.messages]
        return SessionHistoryResponse(
            session_id=session_data.session_id,
            customer_id=session_data.customer_id,
            messages=messages_list,
            status=session_data.status.value if hasattr(session_data.status, "value") else str(session_data.status),
            created_at=session_data.created_at.isoformat() if session_data.created_at else None,
            updated_at=session_data.updated_at.isoformat() if session_data.updated_at else None,
        )
    except ResourceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chat session '{clean_id}' was not found.",
        )
    except Exception as exc:
        logger.error("Error retrieving session history: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session transcript.",
        )


# -----------------------------------------------------------------------------
# 4. Global Live Visitor Counter Endpoint
# -----------------------------------------------------------------------------

_visitor_lock = asyncio.Lock()
VISITOR_FILE = ROOT_DIR / "data" / "visitor_count.txt"


def _read_visitor_count() -> int:
    """Reads persistent visitor count from disk safely."""
    try:
        if VISITOR_FILE.exists():
            content = VISITOR_FILE.read_text(encoding="utf-8").strip()
            if content.isdigit():
                return int(content)
    except Exception as exc:
        logger.warning("Could not read visitor count file: %s", exc)
    return 0


def _write_visitor_count(count: int) -> None:
    """Persists visitor count to disk."""
    try:
        VISITOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        VISITOR_FILE.write_text(str(count), encoding="utf-8")
    except Exception as exc:
        logger.error("Could not persist visitor count: %s", exc)


@router.get(
    "/api/visitors",
    response_model=VisitorCountResponse,
    summary="Global Live Visitor Counter",
    description="Tracks and increments global unique visitor sessions persisted to storage.",
)
async def get_visitor_count() -> VisitorCountResponse:
    """Atomically increments and returns the global platform visitor count."""
    async with _visitor_lock:
        current_count = _read_visitor_count()
        new_count = current_count + 1
        _write_visitor_count(new_count)
        return VisitorCountResponse(total_visitors=new_count)

