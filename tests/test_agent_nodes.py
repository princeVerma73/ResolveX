"""Unit and integration tests for ResolveX Agent Execution Nodes (Step 6 — Phase 2).

Verifies:
1. `policy_rag_node`:
   - Full orchestration of retrieval, RRF, reranking, and grounded response generation.
   - Handling of empty queries.
   - Graceful error recovery with human escalation flag.
2. `db_lookup_node`:
   - Successful order lookup and details formatting.
   - ResourceNotFoundError handling for missing orders.
   - Support ticket lookup and status synthesis.
   - Customer profile lookup by email and customer_id.
   - Missing entity ID handling with clarification request.
3. `action_engine_node`:
   - Valid order cancellation with status transition.
   - Guard against cancelling already cancelled orders.
   - Guard against cancelling delivered orders.
   - Refund request execution across payment records.
   - Missing order ID handling with clarification flag.
4. `escalation_node`:
   - Human escalation flag setting (`is_escalated = True`).
   - Empathetic handoff message generation and dispatch payload recording.
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

from Backend.agent.nodes import (
    action_engine_node,
    db_lookup_node,
    escalation_node,
    policy_rag_node,
)
from Backend.agent.router import ExtractedEntities, IntentType, RouteDecision
from Backend.agent.state import AgentState
from Backend.core.exceptions import InvalidOperationError, ResourceNotFoundError
from Backend.rag.generation import GroundedResponse
from Backend.rag.reranking import RankedChunk
from Backend.rag.retrieval import RetrievedChunk
from Backend.schemas.common import (
    OrderStatus,
    PaymentStatus,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)

from Backend.schemas.customer import CustomerResponse
from Backend.schemas.order import OrderResponse, OrderWithDetailsResponse
from Backend.schemas.payment import PaymentResponse
from Backend.schemas.ticket import TicketResponse


# =============================================================================
# 1. Policy RAG Node Tests
# =============================================================================

class TestPolicyRAGNode:
    """Test suite for policy_rag_node execution."""

    def test_policy_rag_node_success(self):
        state = AgentState(
            session_id="sess_1",
            current_query="What is the refund window for electronics?",
            route_decision=RouteDecision(
                intent=IntentType.POLICY_INQUIRY,
                confidence=0.98,
                entities=ExtractedEntities(policy_topic="refund"),
            ),
        )

        mock_retriever = MagicMock()
        mock_retriever.retrieve_parallel.return_value = (
            [
                RetrievedChunk(
                    chunk_id="chunk_1",
                    document_name="refund_policy.pdf",
                    section_title="Electronics",
                    chunk_content="Electronics may be returned within 14 days.",
                    score=0.95,
                    retrieval_type="dense",
                )
            ],
            [],
        )

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [
            RankedChunk(
                chunk_id="chunk_1",
                document_name="refund_policy.pdf",
                section_title="Electronics",
                chunk_content="Electronics may be returned within 14 days.",
                score=0.95,
                retrieval_type="hybrid",
                rrf_score=0.016,
                rerank_score=0.95,
                final_rank=1,
            )
        ]

        mock_generator = MagicMock()
        mock_generator.generate_resolution.return_value = GroundedResponse(
            response_text="Electronics can be returned within 14 days of purchase [ID: chunk_1].",
            citations=["chunk_1"],
            is_escalated=False,
            clarification_needed=False,
        )

        updated_state = policy_rag_node(
            state,
            retriever=mock_retriever,
            reranker=mock_reranker,
            generator=mock_generator,
        )

        assert len(updated_state.retrieved_chunks) == 1
        assert updated_state.retrieved_chunks[0].chunk_id == "chunk_1"
        assert "14 days" in updated_state.final_response
        assert updated_state.is_escalated is False
        assert updated_state.clarification_needed is False

    def test_policy_rag_node_empty_query(self):
        state = AgentState(
            session_id="sess_2",
            current_query="",
        )
        updated_state = policy_rag_node(state)
        assert updated_state.clarification_needed is True
        assert "Please provide a query" in updated_state.final_response

    def test_policy_rag_node_exception_handling(self):
        state = AgentState(
            session_id="sess_3",
            current_query="What is your shipping policy?",
        )
        mock_retriever = MagicMock()
        mock_retriever.retrieve_parallel.side_effect = RuntimeError("Embedding API failure")

        updated_state = policy_rag_node(state, retriever=mock_retriever)
        assert updated_state.is_escalated is True
        assert "escalated" in updated_state.final_response.lower()


# =============================================================================
# 2. Database Lookup Node Tests
# =============================================================================

class TestDBLookupNode:
    """Test suite for db_lookup_node execution."""

    def test_db_lookup_order_success(self):
        state = AgentState(
            session_id="sess_10",
            current_query="Where is order ORD-8832?",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.99,
                entities=ExtractedEntities(order_id="ORD-8832"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_with_details.return_value = OrderWithDetailsResponse(
            order_id="ORD-8832",
            customer_id="CUST-101",
            status=OrderStatus.SHIPPED,
            total_amount=Decimal("150.00"),
            currency="USD",
            tracking_number="TRK-9901",
            estimated_delivery=datetime(2026, 10, 1, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            items=[],
            payments=[],
        )

        updated_state = db_lookup_node(state, order_service=mock_order_svc)

        assert updated_state.db_lookup_results["type"] == "order"
        assert updated_state.db_lookup_results["data"]["order_id"] == "ORD-8832"
        assert "ORD-8832" in updated_state.final_response
        assert "SHIPPED" in updated_state.final_response
        assert "TRK-9901" in updated_state.final_response
        assert updated_state.clarification_needed is False

    def test_db_lookup_order_not_found(self):
        state = AgentState(
            session_id="sess_11",
            current_query="Track ORD-9999",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.95,
                entities=ExtractedEntities(order_id="ORD-9999"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_with_details.side_effect = ResourceNotFoundError(
            resource_type="Order", resource_id="ORD-9999"
        )

        updated_state = db_lookup_node(state, order_service=mock_order_svc)

        assert updated_state.db_lookup_results["type"] == "order"
        assert "error" in updated_state.db_lookup_results
        assert "could not find an order" in updated_state.final_response
        assert updated_state.clarification_needed is True

    def test_db_lookup_ticket_success(self):
        state = AgentState(
            session_id="sess_12",
            current_query="Check status of ticket TCK-4001",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.97,
                entities=ExtractedEntities(ticket_id="TCK-4001"),
            ),
        )

        mock_ticket_svc = MagicMock()
        mock_ticket_svc.get_ticket_by_id.return_value = TicketResponse(
            ticket_id="TCK-4001",
            customer_id="CUST-101",
            category=TicketCategory.BILLING,
            priority=TicketPriority.HIGH,
            status=TicketStatus.OPEN,
            subject="Overcharge dispute",
            description="Customer disputed an overcharge on recent order.",
            assigned_agent="Agent Alex",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


        updated_state = db_lookup_node(state, ticket_service=mock_ticket_svc)

        assert updated_state.db_lookup_results["type"] == "ticket"
        assert "TCK-4001" in updated_state.final_response
        assert "Overcharge dispute" in updated_state.final_response
        assert "Agent Alex" in updated_state.final_response

    def test_db_lookup_customer_by_email_success(self):
        state = AgentState(
            session_id="sess_13",
            current_query="Find account for emma@example.com",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.96,
                entities=ExtractedEntities(email="emma@example.com"),
            ),
        )

        mock_cust_svc = MagicMock()
        mock_cust_svc.get_customer_by_email.return_value = CustomerResponse(
            customer_id="CUST-770",
            full_name="Emma Watson",
            email="emma@example.com",
            tier="PLATINUM",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated_state = db_lookup_node(state, customer_service=mock_cust_svc)

        assert updated_state.db_lookup_results["type"] == "customer"
        assert "Emma Watson" in updated_state.final_response
        assert "PLATINUM" in updated_state.final_response

    def test_db_lookup_customer_by_id_success(self):
        state = AgentState(
            session_id="sess_14",
            current_query="Look up my profile CUST-101",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.96,
                entities=ExtractedEntities(customer_id="CUST-101"),
            ),
        )

        mock_cust_svc = MagicMock()
        mock_cust_svc.get_customer_by_id.return_value = CustomerResponse(
            customer_id="CUST-101",
            full_name="John Doe",
            email="john@example.com",
            tier="GOLD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated_state = db_lookup_node(state, customer_service=mock_cust_svc)

        assert updated_state.db_lookup_results["type"] == "customer"
        assert "John Doe" in updated_state.final_response
        assert "CUST-101" in updated_state.final_response

    def test_db_lookup_missing_all_entities(self):
        state = AgentState(
            session_id="sess_15",
            current_query="Where is my stuff?",
            route_decision=RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.80,
                entities=ExtractedEntities(),
            ),
        )
        updated_state = db_lookup_node(state)
        assert updated_state.clarification_needed is True
        assert "please provide your order ID" in updated_state.final_response


# =============================================================================
# 3. Action Engine Node Tests
# =============================================================================

class TestActionEngineNode:
    """Test suite for action_engine_node execution."""

    def test_action_engine_cancel_order_success(self):
        state = AgentState(
            session_id="sess_20",
            current_query="Please cancel order ORD-5511",
            route_decision=RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.98,
                entities=ExtractedEntities(order_id="ORD-5511", action_type="cancel_order"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-5511",
            customer_id="CUST-101",
            status=OrderStatus.PENDING,
            total_amount=Decimal("50.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated_state = action_engine_node(state, order_service=mock_order_svc)

        assert updated_state.action_results["status"] == "success"
        assert updated_state.action_results["new_status"] == "CANCELLED"
        assert "successfully cancelled" in updated_state.final_response
        mock_order_svc.update_order_status.assert_called_once_with("ORD-5511", OrderStatus.CANCELLED)

    def test_action_engine_cancel_delivered_order_rejected(self):
        state = AgentState(
            session_id="sess_21",
            current_query="Cancel ORD-1001",
            route_decision=RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.95,
                entities=ExtractedEntities(order_id="ORD-1001", action_type="cancel_order"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-1001",
            customer_id="CUST-101",
            status=OrderStatus.DELIVERED,
            total_amount=Decimal("75.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated_state = action_engine_node(state, order_service=mock_order_svc)

        assert updated_state.action_results["status"] == "failed"
        assert "Cannot cancel delivered order" in updated_state.action_results["reason"]
        assert "cannot be cancelled because it has already been delivered" in updated_state.final_response
        mock_order_svc.update_order_status.assert_not_called()

    def test_action_engine_cancel_already_cancelled_order(self):
        state = AgentState(
            session_id="sess_22",
            current_query="Cancel ORD-2002",
            route_decision=RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.95,
                entities=ExtractedEntities(order_id="ORD-2002", action_type="cancel_order"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-2002",
            customer_id="CUST-101",
            status=OrderStatus.CANCELLED,
            total_amount=Decimal("30.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated_state = action_engine_node(state, order_service=mock_order_svc)

        assert updated_state.action_results["status"] == "failed"
        assert "already cancelled" in updated_state.final_response

    def test_action_engine_request_refund_success(self):
        state = AgentState(
            session_id="sess_23",
            current_query="Refund order ORD-3301",
            route_decision=RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.97,
                entities=ExtractedEntities(order_id="ORD-3301", action_type="request_refund"),
            ),
        )

        mock_order_svc = MagicMock()
        mock_order_svc.get_order_by_id.return_value = OrderResponse(
            order_id="ORD-3301",
            customer_id="CUST-101",
            status=OrderStatus.CANCELLED,
            total_amount=Decimal("80.00"),
            currency="USD",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_payment_svc = MagicMock()
        mock_payment_svc.get_payments_by_order_id.return_value = [
            PaymentResponse(
                payment_id="PAY-501",
                order_id="ORD-3301",
                amount=Decimal("80.00"),
                status=PaymentStatus.SUCCESS,
                payment_method="CREDIT_CARD",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        ]

        updated_state = action_engine_node(
            state, order_service=mock_order_svc, payment_service=mock_payment_svc
        )

        assert updated_state.action_results["status"] == "success"
        assert "PAY-501" in updated_state.action_results["refunded_payments"]
        assert "refund request for order ORD-3301 has been processed" in updated_state.final_response
        mock_payment_svc.update_payment_status.assert_called_once()

    def test_action_engine_missing_order_id(self):
        state = AgentState(
            session_id="sess_24",
            current_query="Cancel my order please",
            route_decision=RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.90,
                entities=ExtractedEntities(action_type="cancel_order"),
            ),
        )

        updated_state = action_engine_node(state)

        assert updated_state.action_results["status"] == "failed"
        assert updated_state.clarification_needed is True
        assert "please provide the specific order ID" in updated_state.final_response


# =============================================================================
# 4. Human Escalation Node Tests
# =============================================================================

class TestEscalationNode:
    """Test suite for escalation_node execution."""

    def test_escalation_node_sets_flags_and_payload(self):
        state = AgentState(
            session_id="sess_30",
            customer_id="CUST-505",
            current_query="I want to speak with your manager immediately",
            route_decision=RouteDecision(
                intent=IntentType.GENERAL_ESCALATION,
                confidence=0.99,
                reasoning="Customer requested human supervisor handoff",
            ),
        )

        updated_state = escalation_node(state)

        assert updated_state.is_escalated is True
        assert "escalated to our human support team" in updated_state.final_response
        assert "escalation_payload" in updated_state.action_results
        payload = updated_state.action_results["escalation_payload"]
        assert payload["session_id"] == "sess_30"
        assert payload["customer_id"] == "CUST-505"
        assert payload["status"] == "ESCALATED"
        assert payload["reason"] == "Customer requested human supervisor handoff"
