"""ResolveX Enterprise Multi-Agent Support API & WebSocket Platform.

Step 7: API Layer & WebSocket Chat.
"""

from __future__ import annotations

import asyncio
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

# Default keep-alive interval: 12 hours (43,200 seconds)
SUPABASE_KEEP_ALIVE_INTERVAL_SECONDS = int(
    os.getenv("SUPABASE_KEEP_ALIVE_INTERVAL", str(12 * 60 * 60))
)


# -----------------------------------------------------------------------------
# 1. Supabase Anti-Sleep Keep-Alive Background Service
# -----------------------------------------------------------------------------

def ping_supabase_db() -> bool:
    """Performs a lightweight query to Supabase to prevent the free tier from pausing."""
    try:
        from Backend.db.supabase_client import get_supabase_client

        client = get_supabase_client()
        # Lightweight probe: query a single row from customers or chat_sessions
        try:
            client.table("customers").select("customer_id", count="exact").limit(1).execute()
        except Exception:
            client.table("chat_sessions").select("session_id", count="exact").limit(1).execute()

        logger.info("Supabase anti-sleep keep-alive ping succeeded.")
        return True
    except Exception as exc:
        logger.warning("Supabase keep-alive ping attempt failed: %s", exc)
        return False


async def supabase_anti_sleep_task(
    interval_seconds: int = SUPABASE_KEEP_ALIVE_INTERVAL_SECONDS,
) -> None:
    """Asynchronous background loop that pings Supabase periodically to prevent inactivity pausing."""
    logger.info(
        "Started Supabase anti-sleep background task (interval=%d seconds).",
        interval_seconds,
    )
    while True:
        try:
            await asyncio.to_thread(ping_supabase_db)
        except Exception as exc:
            logger.warning("Error during Supabase keep-alive ping execution: %s", exc)

        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Supabase anti-sleep background task cancelled.")
            break


# -----------------------------------------------------------------------------
# 2. Lifespan Management
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

    # Start Supabase anti-sleep keep-alive background task (runs every 12 hours)
    keep_alive_task = asyncio.create_task(supabase_anti_sleep_task())
    app.state.keep_alive_task = keep_alive_task

    yield

    logger.info("Shutting down ResolveX API services...")
    if keep_alive_task and not keep_alive_task.done():
        keep_alive_task.cancel()
        try:
            await keep_alive_task
        except asyncio.CancelledError:
            pass


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

    # Configure CORS for frontend web, Netlify deployments, and dashboard clients
    allowed_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"^https:\/\/[a-zA-Z0-9_.-]+\.netlify\.app$",
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
