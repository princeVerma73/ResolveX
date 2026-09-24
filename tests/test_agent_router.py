"""Unit and integration tests for ResolveX Intent Router and Agent State (Step 6 — Phase 1).

Verifies:
1. AgentState data model instantiation, default field bindings, and state propagation.
2. IntentType enum values and ExtractedEntities field validation.
3. RouteDecision structured output validation and confidence bounds.
4. IntentRouter classification into all 4 core intent domains:
   - POLICY_INQUIRY
   - DATABASE_LOOKUP (with order_id / email extraction)
   - ACTION_EXECUTION (with order_id and action_type extraction)
   - GENERAL_ESCALATION
5. Multi-turn conversation history formatting in intent routing prompt.
6. Heuristic fallback classification on transient API failures.
7. Edge cases: empty queries, whitespace queries, markdown wrapped JSON responses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.router import (
    DEFAULT_ROUTER_MODEL,
    ExtractedEntities,
    IntentRouter,
    IntentType,
    RouteDecision,
)
from Backend.agent.state import AgentState


# =============================================================================
# 1. State & Domain Model Tests
# =============================================================================

class TestAgentStateAndModels:
    """Test suite for AgentState, RouteDecision, and ExtractedEntities."""

    def test_agent_state_instantiation_defaults(self):
        state = AgentState(
            session_id="sess_101",
            current_query="Where is my order?",
        )
        assert state.session_id == "sess_101"
        assert state.customer_id is None
        assert state.current_query == "Where is my order?"
        assert state.messages == []
        assert state.route_decision is None
        assert state.retrieved_chunks == []
        assert state.db_lookup_results == {}
        assert state.action_results == {}
        assert state.final_response is None
        assert state.is_escalated is False
        assert state.clarification_needed is False

    def test_extracted_entities_all_fields_optional(self):
        entities = ExtractedEntities(
            order_id="ORD-9912",
            email="sarah@example.com",
            customer_id="CUST-002",
            ticket_id="TCK-404",
            policy_topic="refund",
            action_type="cancel_order",
        )
        assert entities.order_id == "ORD-9912"
        assert entities.email == "sarah@example.com"
        assert entities.customer_id == "CUST-002"
        assert entities.ticket_id == "TCK-404"
        assert entities.policy_topic == "refund"
        assert entities.action_type == "cancel_order"

    def test_route_decision_confidence_bounds(self):
        decision = RouteDecision(
            intent=IntentType.POLICY_INQUIRY,
            confidence=0.95,
            entities=ExtractedEntities(policy_topic="shipping"),
            reasoning="User asking about standard delivery timeframes",
        )
        assert decision.intent == IntentType.POLICY_INQUIRY
        assert decision.confidence == 0.95
        assert decision.entities.policy_topic == "shipping"

        # Confidence out of bounds (< 0.0 or > 1.0) raises validation error
        with pytest.raises(Exception):
            RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=1.5,
                entities=ExtractedEntities(),
            )


# =============================================================================
# 2. IntentRouter Classification Tests (Mocked LLM)
# =============================================================================

class TestIntentRouterClassification:
    """Test suite for IntentRouter classification across all 4 intent types."""

    def test_classify_empty_query_raises_value_error(self):
        router = IntentRouter()
        with pytest.raises(ValueError, match="cannot be empty"):
            router.classify_intent("")
        with pytest.raises(ValueError, match="cannot be empty"):
            router.classify_intent("   ")

    def test_classify_policy_inquiry(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "POLICY_INQUIRY",
            "confidence": 0.98,
            "entities": {
                "policy_topic": "refund",
                "order_id": None,
                "email": None,
                "customer_id": None,
                "ticket_id": None,
                "action_type": None,
            },
            "reasoning": "Inquiring about refund terms for unsealed products.",
        })
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        decision = router.classify_intent("What is your refund policy for opened items?")

        assert decision.intent == IntentType.POLICY_INQUIRY
        assert decision.confidence == 0.98
        assert decision.entities.policy_topic == "refund"
        assert "refund terms" in decision.reasoning

    def test_classify_database_lookup_with_extracted_order_id(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "DATABASE_LOOKUP",
            "confidence": 0.99,
            "entities": {
                "order_id": "ORD-8832",
                "email": None,
                "customer_id": None,
                "ticket_id": None,
                "policy_topic": None,
                "action_type": None,
            },
            "reasoning": "User is checking tracking and delivery status for order ORD-8832.",
        })
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        decision = router.classify_intent("Where is my order ORD-8832?")

        assert decision.intent == IntentType.DATABASE_LOOKUP
        assert decision.confidence == 0.99
        assert decision.entities.order_id == "ORD-8832"

    def test_classify_action_execution_with_extracted_action_type(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "ACTION_EXECUTION",
            "confidence": 0.97,
            "entities": {
                "order_id": "ORD-5511",
                "action_type": "cancel_order",
                "email": None,
                "customer_id": None,
                "ticket_id": None,
                "policy_topic": None,
            },
            "reasoning": "User explicitly requests immediate cancellation of order ORD-5511.",
        })
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        decision = router.classify_intent("Please cancel my order ORD-5511 immediately")

        assert decision.intent == IntentType.ACTION_EXECUTION
        assert decision.confidence == 0.97
        assert decision.entities.order_id == "ORD-5511"
        assert decision.entities.action_type == "cancel_order"

    def test_classify_general_escalation(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "GENERAL_ESCALATION",
            "confidence": 0.95,
            "entities": {
                "order_id": None,
                "email": None,
                "customer_id": None,
                "ticket_id": None,
                "policy_topic": None,
                "action_type": None,
            },
            "reasoning": "Customer requests executive escalation to the company CEO.",
        })
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        decision = router.classify_intent("I want to talk to your CEO right now")

        assert decision.intent == IntentType.GENERAL_ESCALATION
        assert decision.confidence == 0.95

    def test_classify_markdown_wrapped_json_response(self):
        """Verify resilience when Gemini returns markdown code blocks ```json ... ```."""
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "```json\n" + json.dumps({
            "intent": "POLICY_INQUIRY",
            "confidence": 0.92,
            "entities": {"policy_topic": "shipping"},
            "reasoning": "Shipping duration query",
        }) + "\n```"
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        decision = router.classify_intent("How long does shipping take?")

        assert decision.intent == IntentType.POLICY_INQUIRY
        assert decision.confidence == 0.92

    def test_classify_with_conversation_history(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "ACTION_EXECUTION",
            "confidence": 0.96,
            "entities": {"order_id": "ORD-1234", "action_type": "cancel_order"},
            "reasoning": "Context confirms user wants to cancel order ORD-1234 discussed in previous turn.",
        })
        mock_genai.models.generate_content.return_value = mock_response

        router = IntentRouter(genai_client=mock_genai)
        history = [
            {"role": "user", "content": "I ordered ORD-1234 yesterday."},
            {"role": "assistant", "content": "Your order ORD-1234 is currently processing."},
        ]
        decision = router.classify_intent("Please cancel it", history=history)

        assert decision.intent == IntentType.ACTION_EXECUTION
        assert decision.entities.order_id == "ORD-1234"
        _, kwargs = mock_genai.models.generate_content.call_args
        assert "ORD-1234" in kwargs["contents"]


# =============================================================================
# 3. Heuristic Fallback Tests
# =============================================================================

class TestHeuristicFallback:
    """Test suite for offline regex-based fallback classification."""

    def test_fallback_on_api_error_action_keywords(self):
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError("API Quota 429")

        router = IntentRouter(genai_client=mock_genai, max_retries=1)
        decision = router.classify_intent("Please cancel order ORD-7711")

        assert decision.intent == IntentType.ACTION_EXECUTION
        assert decision.entities.order_id == "ORD-7711"
        assert decision.entities.action_type == "cancel_order"
        assert "Heuristic match" in decision.reasoning

    def test_fallback_on_api_error_database_lookup(self):
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError("Connection timeout")

        router = IntentRouter(genai_client=mock_genai, max_retries=1)
        decision = router.classify_intent("Where is my package ORD-3321?")

        assert decision.intent == IntentType.DATABASE_LOOKUP
        assert decision.entities.order_id == "ORD-3321"

    def test_fallback_on_api_error_escalation(self):
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError("Service 503")

        router = IntentRouter(genai_client=mock_genai, max_retries=1)
        decision = router.classify_intent("I want to speak with a human manager")

        assert decision.intent == IntentType.GENERAL_ESCALATION

    def test_fallback_on_api_error_default_policy(self):
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError("Network error")

        router = IntentRouter(genai_client=mock_genai, max_retries=1)
        decision = router.classify_intent("What is your standard return window?")

        assert decision.intent == IntentType.POLICY_INQUIRY
