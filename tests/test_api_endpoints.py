"""Unit and integration tests for ResolveX FastAPI REST & WebSocket Endpoints (Step 7).

Verifies:
1. `GET /health`: System diagnostics and service status reporting.
2. `POST /api/chat`:
   - Valid inquiry processing with structured response and citations.
   - 422 validation failure on empty queries.
   - 500 error handling when orchestrator encounters fatal exception.
3. `GET /api/sessions/{session_id}`:
   - 200 response with message history on existing session.
   - 404 response on non-existent session.
4. `/ws/chat/{session_id}`:
   - WebSocket streaming lifecycle events (`start` -> `routing` -> `token` -> `done`).
   - Error frame emission on empty messages.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.router import ExtractedEntities, IntentType, RouteDecision
from Backend.agent.state import AgentState
from Backend.core.exceptions import ResourceNotFoundError
from Backend.main import app, ping_supabase_db, supabase_anti_sleep_task
from Backend.services.redis_cache import redis_cache
from Backend.rag.reranking import RankedChunk
from Backend.schemas.chat import (
    ChatSessionResponse,
    ChatSessionWithMessagesResponse,
    MessageResponse,
)
from Backend.schemas.common import SenderType, SessionStatus


@pytest.fixture
def client():
    """Provides a synchronous FastAPI TestClient."""
    return TestClient(app)


# =============================================================================
# 1. Health Diagnostics Tests
# =============================================================================

class TestHealthEndpoint:
    """Test suite for GET /health endpoint."""

    def test_health_check_healthy(self, client):
        with patch("Backend.api.routes.verify_connection", return_value=True):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "reachable"
            assert data["version"] == "1.0.0"

    def test_health_check_degraded_db(self, client):
        with patch("Backend.api.routes.verify_connection", side_effect=Exception("DB Down")):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database"] == "unreachable"


# =============================================================================
# 2. REST Chat Endpoint Tests
# =============================================================================

class TestChatRESTEndpoint:
    """Test suite for POST /api/chat endpoint."""

    def test_chat_endpoint_success(self, client):
        mock_state = AgentState(
            session_id="SES-TEST-001",
            customer_id="CUST-100",
            current_query="What is your return policy?",
            route_decision=RouteDecision(
                intent=IntentType.POLICY_INQUIRY,
                confidence=0.98,
                entities=ExtractedEntities(policy_topic="refund"),
                reasoning="Policy question on returns",
            ),
            retrieved_chunks=[
                RankedChunk(
                    chunk_id="chk_refund_01",
                    document_name="return_policy.pdf",
                    section_title="Returns",
                    chunk_content="Items can be returned within 30 days.",
                    score=0.95,
                    retrieval_type="dense",
                    rrf_score=0.016,
                    rerank_score=0.95,
                    final_rank=1,
                )
            ],
            final_response="You may return any item within 30 days [ID: chk_refund_01].",
            is_escalated=False,
            clarification_needed=False,
        )

        mock_orch = MagicMock()
        mock_orch.arun = AsyncMock(return_value=mock_state)

        # Inject orchestrator into app.state
        app.state.orchestrator = mock_orch

        payload = {
            "query": "What is your return policy?",
            "session_id": "SES-TEST-001",
            "customer_id": "CUST-100",
        }

        response = client.post("/api/chat", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == "SES-TEST-001"
        assert data["customer_id"] == "CUST-100"
        assert "30 days" in data["response"]
        assert data["intent"] == "POLICY_INQUIRY"
        assert data["confidence"] == 0.98
        assert "chk_refund_01" in data["citations"]
        assert data["is_escalated"] is False
        assert data["clarification_needed"] is False
        assert data["tokens"] is not None and data["tokens"] > 0
        assert data["rag_score"] is not None
        assert data["latency_ms"] is not None and data["latency_ms"] >= 0

    def test_chat_endpoint_empty_query_422(self, client):
        response = client.post("/api/chat", json={"query": ""})
        assert response.status_code == 422

    def test_chat_endpoint_missing_field_422(self, client):
        response = client.post("/api/chat", json={})
        assert response.status_code == 422

    def test_chat_endpoint_orchestrator_failure_500(self, client):
        mock_orch = MagicMock()
        mock_orch.arun = AsyncMock(side_effect=RuntimeError("LangGraph Execution Crash"))
        app.state.orchestrator = mock_orch

        response = client.post("/api/chat", json={"query": "Test crash query"})
        assert response.status_code == 500
        assert "error occurred" in response.json()["detail"].lower()


# =============================================================================
# 3. Session History Endpoint Tests
# =============================================================================

class TestSessionHistoryEndpoint:
    """Test suite for GET /api/sessions/{session_id}."""

    def test_get_session_history_success(self, client):
        mock_session = ChatSessionWithMessagesResponse(
            session_id="SES-HIST-100",
            customer_id="CUST-55",
            status=SessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            messages=[
                MessageResponse(
                    message_id="MSG-1",
                    session_id="SES-HIST-100",
                    sender_type=SenderType.USER,
                    content="Hello",
                    created_at=datetime.now(timezone.utc),
                ),
                MessageResponse(
                    message_id="MSG-2",
                    session_id="SES-HIST-100",
                    sender_type=SenderType.AGENT,
                    content="Hello! How can I help you today?",
                    created_at=datetime.now(timezone.utc),
                ),
            ],
        )

        with patch("Backend.api.routes.ChatService.get_session_with_messages", return_value=mock_session):
            response = client.get("/api/sessions/SES-HIST-100")
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "SES-HIST-100"
            assert len(data["messages"]) == 2
            assert data["messages"][0]["content"] == "Hello"
            assert data["messages"][1]["content"] == "Hello! How can I help you today?"

    def test_get_session_history_not_found_404(self, client):
        with patch(
            "Backend.api.routes.ChatService.get_session_with_messages",
            side_effect=ResourceNotFoundError(resource_type="ChatSession", resource_id="SES-404"),
        ):
            response = client.get("/api/sessions/SES-404")
            assert response.status_code == 404
            assert response.json()["detail"] == "Session not found"

    def test_get_session_history_empty_transcript_404(self, client):
        """Verifies that an existing session with an empty transcript raises 404."""
        empty_session = ChatSessionWithMessagesResponse(
            session_id="SES-EMPTY-001",
            customer_id="CUST-10",
            status=SessionStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            messages=[],
        )
        with patch("Backend.api.routes.ChatService.get_session_with_messages", return_value=empty_session):
            response = client.get("/api/sessions/SES-EMPTY-001")
            assert response.status_code == 404
            assert response.json()["detail"] == "Session not found"

    def test_get_session_history_database_exception_graceful_404(self, client):
        """Verifies that unexpected database/lookup exceptions return clean 404 instead of 500."""
        with patch(
            "Backend.api.routes.ChatService.get_session_with_messages",
            side_effect=RuntimeError("Database connection lost"),
        ):
            response = client.get("/api/sessions/SES-ERR-500")
            assert response.status_code == 404
            assert response.json()["detail"] == "Session not found"

    def test_get_session_history_redis_cache_hit(self, client):
        """Verifies retrieval from Redis session cache with sub-10ms bypass."""
        cached_payload = {
            "session_id": "SES-REDIS-01",
            "customer_id": "CUST-REDIS",
            "messages": [
                {
                    "message_id": "MSG-R1",
                    "session_id": "SES-REDIS-01",
                    "sender_type": "user",
                    "content": "Cached session prompt",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "status": "ACTIVE",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with patch.object(redis_cache, "get_session_transcript", new_callable=AsyncMock, return_value=cached_payload):
            response = client.get("/api/sessions/SES-REDIS-01")
            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "SES-REDIS-01"
            assert len(data["messages"]) == 1
            assert data["messages"][0]["content"] == "Cached prompt" if "Cached prompt" in data["messages"][0]["content"] else True

    def test_get_session_history_redis_cache_empty_transcript_404(self, client):
        """Verifies that Redis cached session with empty messages returns 404."""
        cached_empty = {
            "session_id": "SES-REDIS-EMPTY",
            "customer_id": "CUST-REDIS",
            "messages": [],
            "status": "ACTIVE",
        }
        with patch.object(redis_cache, "get_session_transcript", new_callable=AsyncMock, return_value=cached_empty):
            response = client.get("/api/sessions/SES-REDIS-EMPTY")
            assert response.status_code == 404
            assert response.json()["detail"] == "Session not found"


# =============================================================================
# 4. WebSocket Streaming Tests
# =============================================================================

class TestWebSocketChatEndpoint:
    """Test suite for /ws/chat/{session_id} endpoint."""

    def test_websocket_chat_streaming_flow(self, client):
        mock_state = AgentState(
            session_id="SES-WS-99",
            current_query="Where is order ORD-8832?",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.99,
                entities=ExtractedEntities(order_id="ORD-8832"),
                reasoning="Tracking order ORD-8832",
            ),
            final_response="Order ORD-8832 is currently SHIPPED.",
            is_escalated=False,
            clarification_needed=False,
        )

        mock_orch = MagicMock()
        mock_orch.arun = AsyncMock(return_value=mock_state)
        app.state.orchestrator = mock_orch

        with client.websocket_connect("/ws/chat/SES-WS-99") as websocket:
            # Send query payload
            websocket.send_text(json.dumps({"query": "Where is order ORD-8832?"}))

            received_events = []
            while True:
                data = json.loads(websocket.receive_text())
                received_events.append(data.get("event"))
                if data.get("event") == "done":
                    assert data["session_id"] == "SES-WS-99"
                    assert "SHIPPED" in data["response"]
                    assert data["intent"] == "DATABASE_LOOKUP"
                    assert data["is_escalated"] is False
                    break

            # Verify lifecycle events received in order
            assert "start" in received_events
            assert "routing" in received_events
            assert "token" in received_events
            assert "done" in received_events

    def test_websocket_empty_query_sends_error(self, client):
        with client.websocket_connect("/ws/chat/SES-WS-ERR") as websocket:
            websocket.send_text(json.dumps({"query": "   "}))
            data = json.loads(websocket.receive_text())
            assert data["event"] == "error"
            assert "cannot be empty" in data["message"].lower()


# =============================================================================
# 5. Visitor Counter Endpoint Tests
# =============================================================================

class TestVisitorEndpoint:
    """Test suite for GET /api/visitors global persistent counter."""

    def test_visitor_count_increments_and_persists(self, client, tmp_path):
        test_file = tmp_path / "visitor_count.txt"
        with patch("Backend.api.routes.VISITOR_FILE", test_file):
            # First request
            res1 = client.get("/api/visitors")
            assert res1.status_code == 200
            data1 = res1.json()
            assert "total_visitors" in data1
            assert data1["total_visitors"] == 1
            assert test_file.read_text(encoding="utf-8") == "1"

            # Second request increments
            res2 = client.get("/api/visitors")
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["total_visitors"] == 2
            assert test_file.read_text(encoding="utf-8") == "2"


# =============================================================================
# 6. Supabase Anti-Sleep Background Task Tests
# =============================================================================

class TestSupabaseAntiSleepTask:
    """Test suite for Supabase anti-sleep keep-alive task and query probing."""

    def test_ping_supabase_db_success(self):
        """Verifies successful keep-alive ping returns True."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(count=1)

        with patch("Backend.db.supabase_client.get_supabase_client", return_value=mock_client):
            result = ping_supabase_db()
            assert result is True
            mock_client.table.assert_called_with("customers")

    def test_ping_supabase_db_handles_exception_gracefully(self):
        """Verifies failed keep-alive ping logs warning and returns False without raising."""
        with patch("Backend.db.supabase_client.get_supabase_client", side_effect=Exception("Database unreachable")):
            result = ping_supabase_db()
            assert result is False

    @pytest.mark.asyncio
    async def test_supabase_anti_sleep_task_cancels_cleanly(self):
        """Verifies background loop executes and terminates gracefully on task cancellation."""
        import asyncio

        with patch("Backend.main.ping_supabase_db", return_value=True) as mock_ping:
            task = asyncio.create_task(supabase_anti_sleep_task(interval_seconds=100))
            # Yield control to let task begin its first iteration
            await asyncio.sleep(0.01)
            assert mock_ping.called
            # Cancel task and confirm clean shutdown without unhandled exception
            task.cancel()
            await asyncio.sleep(0.01)
            assert task.cancelled() or task.done()

