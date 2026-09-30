"""ResolveX API Layer Package (Step 7).

Provides FastAPI REST endpoints, real-time WebSocket chat streaming,
and Pydantic schemas for frontend client communication.
"""

from Backend.api.routes import router as chat_router
from Backend.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    SessionHistoryResponse,
)
from Backend.api.websocket import ConnectionManager, manager, router as websocket_router

__all__ = [
    "chat_router",
    "websocket_router",
    "ConnectionManager",
    "manager",
    "ChatRequest",
    "ChatResponse",
    "SessionHistoryResponse",
    "HealthResponse",
]
