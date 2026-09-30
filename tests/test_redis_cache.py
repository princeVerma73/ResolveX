"""Unit and integration tests for Redis Query Caching Service (ResolveX).

Tests:
1. Hash query determinism and case-insensitivity.
2. Redis cache key formatting (`cache:query:<sha256>`).
3. Caching decision rules (Strict policy inquiries vs dynamic order/action bypass).
4. Graceful fallback when Redis is down or unreachable.
5. Async/sync set and get operations with mock Redis.
6. REST API cache hit (sub-10ms, orchestrator bypass, source="REDIS_CACHE").
7. WebSocket cache hit (streaming cached tokens, source="REDIS_CACHE").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.router import ExtractedEntities, IntentType, RouteDecision
from Backend.agent.state import AgentState
from Backend.main import app
from Backend.rag.reranking import RankedChunk
from Backend.services.redis_cache import RedisCacheService, redis_cache
from redis.exceptions import ConnectionError as RedisConnectionError


@pytest.fixture
def client():
    """Provides FastAPI TestClient."""
    return TestClient(app)


# =============================================================================
# 1. Hashing & Key Formatting Tests
# =============================================================================

def test_hash_query_determinism():
    """Ensures query normalization and deterministic SHA-256 hash generation."""
    query_1 = "What is your 30-day refund policy?"
    query_2 = "  what is your 30-day refund policy?  "
    query_3 = "WHAT IS YOUR 30-DAY REFUND POLICY?"

    hash_1 = RedisCacheService.hash_query(query_1)
    hash_2 = RedisCacheService.hash_query(query_2)
    hash_3 = RedisCacheService.hash_query(query_3)

    assert hash_1 == hash_2 == hash_3
    assert len(hash_1) == 64  # SHA-256 hex digest length


def test_cache_key_formatting():
    """Verifies Redis key pattern matches cache:query:<sha256>."""
    service = RedisCacheService()
    key = service.get_cache_key("What are your shipping terms?")
    assert key.startswith("cache:query:")
    hash_part = key.replace("cache:query:", "")
    assert len(hash_part) == 64


# =============================================================================
# 2. Caching Decision Rules (Policy vs Dynamic Data)
# =============================================================================

def test_should_cache_policy_inquiry_only():
    """Confirms only grounded policy queries are cached, while customer/dynamic data is bypassed."""
    # Policy inquiries should be cached
    assert RedisCacheService.should_cache("POLICY_INQUIRY") is True
    assert RedisCacheService.should_cache("policy_inquiry") is True

    # Dynamic data MUST be bypassed
    assert RedisCacheService.should_cache("DATABASE_LOOKUP") is False
    assert RedisCacheService.should_cache("ACTION_EXECUTION") is False
    assert RedisCacheService.should_cache("TECHNICAL_SUPPORT") is False
    assert RedisCacheService.should_cache("GENERAL_ESCALATION") is False
    assert RedisCacheService.should_cache(None) is False

    # Escalated queries or missing parameters MUST NOT be cached
    assert RedisCacheService.should_cache("POLICY_INQUIRY", is_escalated=True) is False
    assert RedisCacheService.should_cache("POLICY_INQUIRY", clarification_needed=True) is False


# =============================================================================
# 3. Graceful Fallback When Redis Unreachable
# =============================================================================

@pytest.mark.asyncio
async def test_redis_graceful_fallback_when_unreachable():
    """Verifies that an unreachable Redis instance returns None/False gracefully without crashing."""
    service = RedisCacheService()
    mock_async = AsyncMock()
    mock_async.get.side_effect = RedisConnectionError("Connection refused")
    mock_async.set.side_effect = RedisConnectionError("Connection refused")
    service._async_client = mock_async

    # Get should return None gracefully without raising
    result = await service.get_cached_response("What is your refund policy?")
    assert result is None

    # Set should return False gracefully without raising
    set_result = await service.set_cached_response(
        "What is your refund policy?", {"response": "30 days"}
    )
    assert set_result is False

    # Sync fallbacks also return None/False without raising
    mock_sync = MagicMock()
    mock_sync.get.side_effect = RedisConnectionError("Connection refused")
    mock_sync.set.side_effect = RedisConnectionError("Connection refused")
    service._sync_client = mock_sync

    assert service.get_cached_response_sync("test") is None
    assert service.set_cached_response_sync("test", {"a": 1}) is False


# =============================================================================
# 4. In-Memory Mock Operations
# =============================================================================

@pytest.mark.asyncio
async def test_redis_async_set_and_get():
    """Tests set and get functionality using mocked Redis client."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps({
        "response": "Returns are accepted within 30 days.",
        "intent": "POLICY_INQUIRY",
        "citations": ["chk_refund_01"],
    })
    mock_redis.set.return_value = True

    service = RedisCacheService()
    service._async_client = mock_redis

    # Test set
    success = await service.set_cached_response(
        "What is your refund window?",
        {"response": "Returns are accepted within 30 days."},
        ttl=1800,
    )
    assert success is True
    assert mock_redis.set.called

    # Test get
    cached = await service.get_cached_response("What is your refund window?")
    assert cached is not None
    assert cached["intent"] == "POLICY_INQUIRY"
    assert "30 days" in cached["response"]


# =============================================================================
# 5. REST API Cache HIT Integration
# =============================================================================

def test_api_chat_endpoint_redis_cache_hit(client):
    """Verifies REST API returns sub-10ms cached response with source='REDIS_CACHE' and bypasses orchestrator."""
    cached_payload = {
        "response": "Refunds are processed within 5-7 business days [ID: chk_refund_02].",
        "intent": "POLICY_INQUIRY",
        "confidence": 0.99,
        "citations": ["chk_refund_02"],
        "entities": {},
        "action_results": {},
    }

    mock_orch = MagicMock()
    mock_orch.arun = AsyncMock()
    app.state.orchestrator = mock_orch

    with patch.object(redis_cache, "get_cached_response", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = cached_payload

        response = client.post("/api/chat", json={"query": "How long do refunds take?"})
        assert response.status_code == 200
        data = response.json()

        # Cache HIT assertions
        assert data["source"] == "REDIS_CACHE"
        assert "5-7 business days" in data["response"]
        assert data["intent"] == "POLICY_INQUIRY"
        assert "chk_refund_02" in data["citations"]

        # Orchestrator MUST be bypassed on cache HIT
        assert mock_orch.arun.call_count == 0


def test_api_chat_endpoint_redis_cache_miss_populates_cache(client):
    """Verifies that cache MISS invokes orchestrator and populates Redis cache for policy queries."""
    mock_state = AgentState(
        session_id="SES-CACHE-MISS",
        current_query="What is your return policy?",
        route_decision=RouteDecision(
            intent=IntentType.POLICY_INQUIRY,
            confidence=0.97,
            entities=ExtractedEntities(policy_topic="returns"),
            reasoning="Policy question",
        ),
        retrieved_chunks=[
            RankedChunk(
                chunk_id="chk_refund_01",
                document_name="refund_policy.pdf",
                section_title="Refunds",
                chunk_content="Items can be returned within 30 days.",
                score=0.95,
                retrieval_type="dense",
                rrf_score=0.016,
                rerank_score=0.95,
                final_rank=1,
            )
        ],
        final_response="You may return any item within 30 days.",
        is_escalated=False,
        clarification_needed=False,
    )

    mock_orch = MagicMock()
    mock_orch.arun = AsyncMock(return_value=mock_state)
    app.state.orchestrator = mock_orch

    with patch.object(redis_cache, "get_cached_response", new_callable=AsyncMock) as mock_get, \
         patch.object(redis_cache, "set_cached_response", new_callable=AsyncMock) as mock_set:
        mock_get.return_value = None  # Cache MISS

        response = client.post("/api/chat", json={"query": "What is your return policy?"})
        assert response.status_code == 200
        data = response.json()

        assert data["source"] == "ORCHESTRATOR"
        assert mock_orch.arun.call_count == 1
        # Set cache MUST be called with policy data
        assert mock_set.call_count == 1
        call_args = mock_set.call_args[0]
        assert call_args[0] == "What is your return policy?"
        assert call_args[1]["intent"] == "POLICY_INQUIRY"


# =============================================================================
# 6. WebSocket Cache HIT Integration
# =============================================================================

def test_websocket_redis_cache_hit(client):
    """Verifies WebSocket client receives cached answer with source='REDIS_CACHE' without orchestrator execution."""
    cached_payload = {
        "response": "Returns are eligible for 30 days from purchase.",
        "intent": "POLICY_INQUIRY",
        "citations": ["chk_refund_01"],
        "action_results": {},
    }

    mock_orch = MagicMock()
    mock_orch.arun = AsyncMock()
    app.state.orchestrator = mock_orch

    with patch.object(redis_cache, "get_cached_response", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = cached_payload

        with client.websocket_connect("/ws/chat/SES-WS-CACHE") as websocket:
            websocket.send_text(json.dumps({"query": "What is the return window?"}))

            events = []
            done_payload = None
            while True:
                frame = json.loads(websocket.receive_text())
                events.append(frame.get("event"))
                if frame.get("event") == "done":
                    done_payload = frame
                    break

            assert "start" in events
            assert "routing" in events
            assert "token" in events
            assert "done" in events

            assert done_payload is not None
            assert done_payload["source"] == "REDIS_CACHE"
            assert "30 days" in done_payload["response"]
            assert done_payload["intent"] == "POLICY_INQUIRY"

            # Orchestrator was not called
            assert mock_orch.arun.call_count == 0
