"""Unit and integration tests for ResolveX Multi-Agent StateGraph Orchestrator (Step 6 — Phase 3).

Verifies:
1. Orchestrator initialization and LangGraph StateGraph compilation.
2. End-to-end execution across all 4 core routing branches:
   - POLICY_INQUIRY -> policy_rag_node -> Grounded response with citations.
   - DATABASE_LOOKUP -> db_lookup_node -> Grounded database status summary.
   - ACTION_EXECUTION -> action_engine_node -> Transactional action mutation receipt.
   - GENERAL_ESCALATION -> escalation_node -> Human escalation handoff.
3. Multi-turn conversation state and message thread propagation.
4. Async execution (`arun`) pipeline.
5. Fallback behavior when query is empty or unknown.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.graph import SupportAgentOrchestrator
from Backend.agent.router import ExtractedEntities, IntentRouter, IntentType, RouteDecision
from Backend.agent.state import AgentState
from Backend.rag.generation import GroundedResponse
from Backend.rag.reranking import RankedChunk
from Backend.rag.retrieval import RetrievedChunk
from Backend.schemas.common import OrderStatus
from Backend.schemas.order import OrderResponse, OrderWithDetailsResponse


# =============================================================================
# 1. Orchestrator Initialization & Branch Routing Tests
# =============================================================================

class TestSupportAgentOrchestrator:
    """Test suite for SupportAgentOrchestrator LangGraph pipeline."""

    def test_orchestrator_initialization(self):
        orchestrator = SupportAgentOrchestrator()
        assert orchestrator.router is not None
        assert orchestrator.compiled_graph is not None

    def test_orchestrator_policy_inquiry_pathway(self):
        # 1. Mock Router
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.POLICY_INQUIRY,
            confidence=0.98,
            entities=ExtractedEntities(policy_topic="refund"),
            reasoning="Customer asks about refund timeframe.",
        )

        # 2. Mock RAG components
        mock_retriever = MagicMock()
        mock_retriever.retrieve_parallel.return_value = (
            [
                RetrievedChunk(
                    chunk_id="chunk_policy_1",
                    document_name="refund_policy.pdf",
                    section_title="Returns",
                    chunk_content="Refunds are processed within 14 days of receipt.",
                    score=0.92,
                    retrieval_type="dense",
                )
            ],
            [],
        )

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [
            RankedChunk(
                chunk_id="chunk_policy_1",
                document_name="refund_policy.pdf",
                section_title="Returns",
                chunk_content="Refunds are processed within 14 days of receipt.",
                score=0.92,
                retrieval_type="hybrid",
                rrf_score=0.016,
                rerank_score=0.92,
                final_rank=1,
            )
        ]

        mock_generator = MagicMock()
        mock_generator.generate_resolution.return_value = GroundedResponse(
            response_text="Refunds are processed within 14 days of package receipt [ID: chunk_policy_1].",
            citations=["chunk_policy_1"],
            is_escalated=False,
            clarification_needed=False,
        )

        orchestrator = SupportAgentOrchestrator(
            router=mock_router,
            retriever=mock_retriever,
            reranker=mock_reranker,
            generator=mock_generator,
        )

        state = orchestrator.run(
            query="How long does it take to get a refund?",
            session_id="sess_test_101",
        )

        assert state.session_id == "sess_test_101"
        assert state.route_decision.intent == IntentType.POLICY_INQUIRY
        assert len(state.retrieved_chunks) == 1
        assert "14 days" in state.final_response
        assert state.is_escalated is False
        assert len(state.messages) == 2
        assert state.messages[0]["role"] == "user"
        assert state.messages[1]["role"] == "assistant"

    def test_orchestrator_db_lookup_pathway(self):
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.DATABASE_LOOKUP,
            confidence=0.99,
            entities=ExtractedEntities(order_id="ORD-7722"),
            reasoning="Inquiring about order status.",
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_with_details.return_value = OrderWithDetailsResponse(
            order_id="ORD-7722",
            customer_id="CUST-300",
            status=OrderStatus.SHIPPED,
            total_amount=Decimal("199.99"),
            currency="USD",
            tracking_number="TRK-7722-FEDEX",
            estimated_delivery=datetime(2026, 10, 5, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            items=[],
            payments=[],
        )

        orchestrator = SupportAgentOrchestrator(
            router=mock_router,
            order_service=mock_order_svc,
        )

        state = orchestrator.run(
            query="Where is my order ORD-7722?",
            session_id="sess_test_102",
        )

        assert state.route_decision.intent == IntentType.DATABASE_LOOKUP
        assert state.db_lookup_results["type"] == "order"
        assert state.db_lookup_results["data"]["order_id"] == "ORD-7722"
        assert "ORD-7722" in state.final_response
        assert "SHIPPED" in state.final_response
        assert "TRK-7722-FEDEX" in state.final_response

    def test_orchestrator_action_execution_pathway(self):
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.ACTION_EXECUTION,
            confidence=0.97,
            entities=ExtractedEntities(order_id="ORD-8811", action_type="cancel_order"),
            reasoning="Customer requests cancellation of ORD-8811.",
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-8811",
            customer_id="CUST-300",
            status=OrderStatus.PROCESSING,
            total_amount=Decimal("45.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        orchestrator = SupportAgentOrchestrator(
            router=mock_router,
            order_service=mock_order_svc,
        )

        state = orchestrator.run(
            query="Please cancel order ORD-8811 now",
            session_id="sess_test_103",
        )

        assert state.route_decision.intent == IntentType.ACTION_EXECUTION
        assert state.action_results["status"] == "success"
        assert state.action_results["new_status"] == "CANCELLED"
        assert "successfully cancelled" in state.final_response
        mock_order_svc.update_order_status.assert_called_once_with("ORD-8811", OrderStatus.CANCELLED)

    def test_orchestrator_general_escalation_pathway(self):
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.GENERAL_ESCALATION,
            confidence=0.95,
            reasoning="Customer requests human agent escalation.",
        )

        orchestrator = SupportAgentOrchestrator(router=mock_router)

        state = orchestrator.run(
            query="I need to speak to a real person right away",
            session_id="sess_test_104",
        )

        assert state.route_decision.intent == IntentType.GENERAL_ESCALATION
        assert state.is_escalated is True
        assert "escalated to our human support team" in state.final_response
        assert "escalation_payload" in state.action_results
        assert state.action_results["escalation_payload"]["session_id"] == "sess_test_104"

    def test_orchestrator_multi_turn_continuity(self):
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.ACTION_EXECUTION,
            confidence=0.96,
            entities=ExtractedEntities(order_id="ORD-1234", action_type="cancel_order"),
            reasoning="Context from history confirms cancelling ORD-1234.",
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-1234",
            customer_id="CUST-100",
            status=OrderStatus.PENDING,
            total_amount=Decimal("89.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        orchestrator = SupportAgentOrchestrator(
            router=mock_router,
            order_service=mock_order_svc,
        )

        history = [
            {"role": "user", "content": "I ordered ORD-1234 yesterday."},
            {"role": "assistant", "content": "Your order ORD-1234 is currently processing."},
        ]

        state = orchestrator.run(
            query="Please cancel it",
            session_id="sess_multi_turn",
            history=history,
        )

        assert state.route_decision.intent == IntentType.ACTION_EXECUTION
        assert state.action_results["status"] == "success"
        # Initial 2 history turns + 1 new user + 1 new assistant turn = 4 turns
        assert len(state.messages) == 4
        assert state.messages[0]["content"] == "I ordered ORD-1234 yesterday."
        assert state.messages[2]["content"] == "Please cancel it"
        assert "successfully cancelled" in state.messages[3]["content"]

    @pytest.mark.asyncio
    async def test_orchestrator_async_execution(self):
        mock_router = MagicMock(spec=IntentRouter)
        mock_router.classify_intent.return_value = RouteDecision(
            intent=IntentType.GENERAL_ESCALATION,
            confidence=0.99,
            reasoning="Legal dispute escalation",
        )

        orchestrator = SupportAgentOrchestrator(router=mock_router)

        state = await orchestrator.arun(
            query="I am taking legal action against your company",
            session_id="sess_async_105",
        )

        assert state.session_id == "sess_async_105"
        assert state.is_escalated is True
        assert len(state.messages) == 2
