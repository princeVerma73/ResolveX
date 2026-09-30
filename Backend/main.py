"""ResolveX Enterprise Multi-Agent Support API & WebSocket Platform.

Step 7: API Layer & WebSocket Chat.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Backend.agent.graph import SupportAgentOrchestrator
from Backend.api.routes import router as chat_router
from Backend.api.websocket import router as websocket_router

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Lifespan Management
# -----------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages application startup and shutdown lifecycle hooks."""
    logger.info("Initializing ResolveX SupportAgentOrchestrator singleton...")
    try:
        # Pre-compile the LangGraph multi-agent orchestrator
        app.state.orchestrator = SupportAgentOrchestrator()
        logger.info("SupportAgentOrchestrator compiled successfully and ready for queries.")
    except Exception as exc:
        logger.warning(
            "Could not pre-initialize SupportAgentOrchestrator at startup (%s). "
            "It will be initialized lazily on the first request.",
            exc,
        )
        app.state.orchestrator = None

    yield

    logger.info("Shutting down ResolveX API services...")


# -----------------------------------------------------------------------------
# 2. Application Factory
# -----------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Builds and configures the FastAPI application instance."""
    app = FastAPI(
        title="ResolveX — AI Customer Support & Resolution Platform",
        description=(
            "Enterprise customer support automation engine with LangGraph multi-agent orchestration "
            "(Triage, Orders, Technical Support, Escalation), grounded RAG, and real-time WebSocket chat streaming."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS for frontend web and dashboard clients
    allowed_origins = os.getenv("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API and WebSocket routers
    app.include_router(chat_router)
    app.include_router(websocket_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("Backend.main:app", host="0.0.0.0", port=port, reload=True)
