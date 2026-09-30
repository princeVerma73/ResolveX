"""WebSocket real-time streaming chat engine and connection manager for ResolveX.

Step 7: API Layer & WebSocket Chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from Backend.agent.graph import SupportAgentOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket Real-Time Chat"])


# -----------------------------------------------------------------------------
# 1. Connection Manager
# -----------------------------------------------------------------------------

class ConnectionManager:
    """Manages active WebSocket client connections across multi-turn chat sessions."""

    def __init__(self) -> None:
        """Initialize active connection tracking registry."""
        self.active_connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accepts and registers a new WebSocket client under a session."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)
        logger.info("WebSocket connected for session: %s (Total: %d)", session_id, len(self.active_connections[session_id]))

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Removes a disconnected client from session tracking."""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        logger.info("WebSocket disconnected for session: %s", session_id)

    async def send_json(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Sends a JSON-serialized frame to a specific client."""
        await websocket.send_text(json.dumps(message))

    async def broadcast_to_session(self, session_id: str, message: dict[str, Any]) -> None:
        """Broadcasts a JSON-serialized message frame to all clients in a session."""
        connections = self.active_connections.get(session_id, set()).copy()
        for connection in connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as exc:
                logger.warning("Error broadcasting frame to client in session %s: %s", session_id, exc)


manager = ConnectionManager()


# -----------------------------------------------------------------------------
# 2. WebSocket Streaming Endpoint
# -----------------------------------------------------------------------------

@router.websocket("/ws/chat/{session_id}")
async def websocket_chat_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Real-time bi-directional streaming chat endpoint for ResolveX.

    WHAT:
        Provides low-latency WebSocket interaction with intermediate lifecycle frames:
        1. `start`: Acknowledges incoming query.
        2. `routing`: Notifies user of intent classification / entity extraction.
        3. `retrieval`: Broadcasts number of grounded passages retrieved (if applicable).
        4. `token`: Streams token deltas for dynamic typewriter rendering.
        5. `done`: Delivers final structured resolution with citations and flags.

    WHY:
        Eliminates perceived latency in conversational AI workflows by streaming status
        and partial responses immediately to the customer UI.
    """
    await manager.connect(websocket, session_id)

    # Access singleton orchestrator from app state if available, else instantiate
    app = websocket.app
    orchestrator: SupportAgentOrchestrator = (
        getattr(app.state, "orchestrator", None) or SupportAgentOrchestrator()
    )

    try:
        while True:
            # 1. Receive incoming message
            raw_data = await websocket.receive_text()
            if not raw_data or not raw_data.strip():
                continue

            query = raw_data.strip()
            customer_id = None
            history = None

            # Attempt JSON payload parsing
            try:
                data = json.loads(raw_data)
                if isinstance(data, dict):
                    query = data.get("query", query).strip()
                    customer_id = data.get("customer_id")
                    history = data.get("history")
            except (json.JSONDecodeError, ValueError):
                pass

            if not query:
                await manager.send_json(
                    websocket,
                    {"event": "error", "message": "Query string cannot be empty."},
                )
                continue

            # 2. Emit 'start' lifecycle event
            await manager.send_json(
                websocket,
                {
                    "event": "start",
                    "session_id": session_id,
                    "query": query,
                },
            )

            # 3. Emit 'routing' lifecycle event
            await manager.send_json(
                websocket,
                {
                    "event": "routing",
                    "status": "Analyzing request intent and extracting domain entities...",
                },
            )

            try:
                # 4. Execute LangGraph multi-agent pipeline
                state = await orchestrator.arun(
                    query=query,
                    session_id=session_id,
                    customer_id=customer_id,
                    history=history,
                )

                # 5. Emit 'retrieval' lifecycle event if chunks were retrieved
                citations = []
                if state.retrieved_chunks:
                    for chunk in state.retrieved_chunks:
                        cid = getattr(chunk, "chunk_id", None)
                        if cid and cid not in citations:
                            citations.append(cid)
                    await manager.send_json(
                        websocket,
                        {
                            "event": "retrieval",
                            "chunks_count": len(state.retrieved_chunks),
                            "citations": citations,
                        },
                    )

                # 6. Stream tokens for dynamic typing effect
                final_text = state.final_response or ""
                words = final_text.split(" ")
                for i, word in enumerate(words):
                    chunk_text = word if i == 0 else " " + word
                    await manager.send_json(
                        websocket,
                        {
                            "event": "token",
                            "delta": chunk_text,
                        },
                    )
                    await asyncio.sleep(0.005)

                # 7. Extract intent & confidence
                intent_val = (
                    state.route_decision.intent.value
                    if state.route_decision and hasattr(state.route_decision.intent, "value")
                    else str(state.route_decision.intent) if state.route_decision and state.route_decision.intent
                    else None
                )

                # 8. Emit 'done' completion event
                await manager.send_json(
                    websocket,
                    {
                        "event": "done",
                        "session_id": session_id,
                        "response": final_text,
                        "intent": intent_val,
                        "citations": citations,
                        "is_escalated": state.is_escalated,
                        "clarification_needed": state.clarification_needed,
                        "action_results": state.action_results,
                    },
                )

            except Exception as exc:
                logger.error("Error processing WebSocket query turn: %s", exc, exc_info=True)
                await manager.send_json(
                    websocket,
                    {
                        "event": "error",
                        "message": f"An error occurred during agent processing: {exc}",
                    },
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as exc:
        logger.error("Unexpected WebSocket error in session %s: %s", session_id, exc)
        manager.disconnect(websocket, session_id)
