"""Decoupled Execution Node Handlers for ResolveX LangGraph multi-agent architecture.

Step 6 — Phase 2: Decoupled Tool Registry & Execution Node Handlers.

WHAT:
    Implements typed worker node functions operating over `AgentState`:
    1. `policy_rag_node`: Executes hybrid search, RRF, cross-encoder reranking, and grounded generation.
    2. `db_lookup_node`: Queries relational domain services (orders, tickets, customers) for read-only tracking.
    3. `action_engine_node`: Executes validated transactional mutations (order cancellation, refunds).
    4. `escalation_node`: Prepares human support agent handoff and escalation payloads.

WHY:
    - Decouples non-deterministic generative RAG workflows from deterministic relational queries and side effects.
    - Standardizes the `AgentState -> AgentState` node interface required for LangGraph graph compilation.
    - Enables 100% offline, deterministic unit testing via dependency-injected domain services.

HOW:
    - Each node function accepts `state: AgentState` along with optional injected service dependencies.
    - Extracts extracted parameters from `state.route_decision.entities`.
    - Mutates appropriate state slots (`retrieved_chunks`, `db_lookup_results`, `action_results`, `final_response`).
    - Implements structured error handling, preserving state consistency without crashing execution.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.state import AgentState
from Backend.core.exceptions import (
    InvalidOperationError,
    ResourceNotFoundError,
    ResolveXException,
)
from Backend.rag.generation import ResolutionGenerator
from Backend.rag.reranking import CrossEncoderReranker, reciprocal_rank_fusion
from Backend.rag.retrieval import HybridRetriever
from Backend.schemas.common import OrderStatus, PaymentStatus
from Backend.schemas.payment import PaymentUpdate
from Backend.services.customer_service import CustomerService
from Backend.services.order_service import OrderService
from Backend.services.payment_service import PaymentService
from Backend.services.ticket_service import TicketService

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Policy RAG Execution Node
# -----------------------------------------------------------------------------

def policy_rag_node(
    state: AgentState,
    retriever: HybridRetriever | None = None,
    reranker: CrossEncoderReranker | None = None,
    generator: ResolutionGenerator | None = None,
) -> AgentState:
    """Executes the Step 5 RAG pipeline to resolve policy inquiries with grounded citations.

    WHAT:
        Runs parallel hybrid retrieval (dense + sparse), reciprocal rank fusion,
        FlashRank cross-encoder reranking, and deterministic Gemini generation.

    WHY:
        Grounds policy responses in verified knowledge base passages with machine-verifiable citations.

    HOW:
        1. Retrieves candidate chunks using `retriever.retrieve_parallel(query, limit=20)`.
        2. Fuses candidate lists with `reciprocal_rank_fusion(dense, sparse, top_n=20)`.
        3. Re-ranks candidates with `reranker.rerank(query, candidates, top_k=3)`.
        4. Synthesizes answer using `generator.generate_resolution(query, ranked_chunks)`.
        5. Hydrates `state.retrieved_chunks`, `state.final_response`, `state.is_escalated`, and `state.clarification_needed`.

    Args:
        state: Incoming conversational AgentState.
        retriever: Optional injected HybridRetriever instance.
        reranker: Optional injected CrossEncoderReranker instance.
        generator: Optional injected ResolutionGenerator instance.

    Returns:
        Updated `AgentState` with grounded response and retrieved passages.
    """
    query = state.current_query.strip()
    if not query:
        state.final_response = "Please provide a query regarding our store policies."
        state.clarification_needed = True
        return state

    retriever_inst = retriever or HybridRetriever()
    reranker_inst = reranker or CrossEncoderReranker()
    generator_inst = generator or ResolutionGenerator()

    try:
        # Step 1: Parallel Hybrid Retrieval
        dense_results, sparse_results = retriever_inst.retrieve_parallel(query, limit=20)

        # Step 2: Reciprocal Rank Fusion
        fused_candidates = reciprocal_rank_fusion(dense_results, sparse_results, top_n=20)

        # Step 3: Cross-Encoder Re-Ranking
        ranked_chunks = reranker_inst.rerank(query=query, candidates=fused_candidates, top_k=3)

        # Step 4: Grounded Generation & Citation Alignment
        grounded_resp = generator_inst.generate_resolution(query=query, ranked_chunks=ranked_chunks)

        # Step 5: State Hydration
        state.retrieved_chunks = list(ranked_chunks)
        state.final_response = grounded_resp.response_text
        state.is_escalated = grounded_resp.is_escalated
        state.clarification_needed = grounded_resp.clarification_needed

    except Exception as exc:
        logger.error("Error during policy_rag_node execution: %s", exc)
        state.final_response = (
            "I apologize, but I encountered an issue retrieving our policy documentation. "
            "Your inquiry has been escalated to a support specialist."
        )
        state.is_escalated = True

    return state


# -----------------------------------------------------------------------------
# 2. Database Lookup Execution Node
# -----------------------------------------------------------------------------

def db_lookup_node(
    state: AgentState,
    order_service: OrderService | None = None,
    ticket_service: TicketService | None = None,
    customer_service: CustomerService | None = None,
    payment_service: PaymentService | None = None,
) -> AgentState:
    """Dispatches read-only database queries and formats customer status summaries.

    WHAT:
        Extracts entity IDs (`order_id`, `ticket_id`, `customer_id`, `email`) and queries
        appropriate relational services to retrieve live operational data.

    WHY:
        Provides instantaneous, zero-hallucination status updates directly from Postgres.

    HOW:
        1. Inspects `state.route_decision.entities`.
        2. Queries `OrderService`, `TicketService`, or `CustomerService`.
        3. Sets `state.db_lookup_results` and formats `state.final_response`.
        4. Handles missing IDs or `ResourceNotFoundError` by requesting clarification.

    Args:
        state: Incoming conversational AgentState.
        order_service: Optional injected OrderService instance.
        ticket_service: Optional injected TicketService instance.
        customer_service: Optional injected CustomerService instance.
        payment_service: Optional injected PaymentService instance.

    Returns:
        Updated `AgentState` containing DB query payload and formatted response.
    """
    order_svc = order_service or OrderService()
    ticket_svc = ticket_service or TicketService()
    customer_svc = customer_service or CustomerService()

    entities = getattr(state.route_decision, "entities", None)
    order_id = getattr(entities, "order_id", None) if entities else None
    ticket_id = getattr(entities, "ticket_id", None) if entities else None
    email = getattr(entities, "email", None) if entities else None
    customer_id = (getattr(entities, "customer_id", None) if entities else None) or state.customer_id

    try:
        # Branch 1: Order Lookup by order_id
        if order_id:
            try:
                order_details = order_svc.get_order_with_details(order_id)
                state.db_lookup_results = {
                    "type": "order",
                    "data": order_details.model_dump(mode="json"),
                }

                tracking_str = (
                    f" Tracking Number: {order_details.tracking_number}."
                    if order_details.tracking_number
                    else ""
                )
                delivery_str = (
                    f" Estimated Delivery: {order_details.estimated_delivery.strftime('%Y-%m-%d')}."
                    if order_details.estimated_delivery
                    else ""
                )
                state.final_response = (
                    f"Order {order_id} is currently {order_details.status}."
                    f"{tracking_str}{delivery_str} "
                    f"Total Amount: {order_details.currency} {order_details.total_amount:.2f}."
                )
                return state

            except ResourceNotFoundError:
                state.db_lookup_results = {
                    "type": "order",
                    "error": f"Order '{order_id}' was not found.",
                }
                state.final_response = (
                    f"I could not find an order with ID '{order_id}'. "
                    f"Please verify your order number and try again."
                )
                state.clarification_needed = True
                return state

        # Branch 2: Ticket Lookup by ticket_id
        if ticket_id:
            try:
                ticket = ticket_svc.get_ticket_by_id(ticket_id)
                state.db_lookup_results = {
                    "type": "ticket",
                    "data": ticket.model_dump(mode="json"),
                }
                assigned_str = f" Assigned Agent: {ticket.assigned_agent}." if ticket.assigned_agent else ""
                state.final_response = (
                    f"Support Ticket {ticket_id} ('{ticket.subject}') is currently {ticket.status} "
                    f"with {ticket.priority} priority.{assigned_str}"
                )
                return state

            except ResourceNotFoundError:
                state.db_lookup_results = {
                    "type": "ticket",
                    "error": f"Ticket '{ticket_id}' was not found.",
                }
                state.final_response = (
                    f"I could not find a support ticket with ID '{ticket_id}'. "
                    f"Please check the ticket number and try again."
                )
                state.clarification_needed = True
                return state

        # Branch 3: Customer Lookup by Email
        if email:
            customer = customer_svc.get_customer_by_email(email)
            if customer:
                state.db_lookup_results = {
                    "type": "customer",
                    "data": customer.model_dump(mode="json"),
                }
                state.final_response = (
                    f"Account found for {customer.full_name} ({customer.email}) — "
                    f"Membership Tier: {customer.tier}."
                )
                return state
            else:
                state.db_lookup_results = {
                    "type": "customer",
                    "error": f"Customer with email '{email}' was not found.",
                }
                state.final_response = f"No customer account was found matching email '{email}'."
                state.clarification_needed = True
                return state

        # Branch 4: Customer Lookup by customer_id
        if customer_id:
            try:
                customer = customer_svc.get_customer_by_id(customer_id)
                state.db_lookup_results = {
                    "type": "customer",
                    "data": customer.model_dump(mode="json"),
                }
                state.final_response = (
                    f"Customer profile for {customer.full_name} ({customer_id}) is active "
                    f"(Tier: {customer.tier})."
                )
                return state
            except ResourceNotFoundError:
                state.db_lookup_results = {
                    "type": "customer",
                    "error": f"Customer ID '{customer_id}' was not found.",
                }
                state.final_response = f"No customer record found with ID '{customer_id}'."
                state.clarification_needed = True
                return state

        # Branch 5: Missing Entity IDs
        state.final_response = (
            "To look up your information, please provide your order ID (e.g. ORD-1234), "
            "ticket ID (e.g. TCK-1001), or account email address."
        )
        state.clarification_needed = True

    except Exception as exc:
        logger.error("Error during db_lookup_node execution: %s", exc)
        state.final_response = (
            "An error occurred while accessing your account records. "
            "Your inquiry has been escalated to our support team."
        )
        state.is_escalated = True

    return state


# -----------------------------------------------------------------------------
# 3. Action Engine Execution Node
# -----------------------------------------------------------------------------

def action_engine_node(
    state: AgentState,
    order_service: OrderService | None = None,
    payment_service: PaymentService | None = None,
    ticket_service: TicketService | None = None,
) -> AgentState:
    """Executes safe domain state mutations with business rule pre-condition validation.

    WHAT:
        Processes state modifications such as order cancellations and refund requests.

    WHY:
        Enforces domain rules (e.g., delivered orders cannot be cancelled) before modifying persistent records.

    HOW:
        1. Validates presence of `order_id` in extracted entities.
        2. Evaluates action type (`cancel_order`, `request_refund`).
        3. Runs domain guards and executes service mutations (`update_order_status`, `update_payment_status`).
        4. Hydrates `state.action_results` receipt and `state.final_response`.

    Args:
        state: Incoming conversational AgentState.
        order_service: Optional injected OrderService instance.
        payment_service: Optional injected PaymentService instance.
        ticket_service: Optional injected TicketService instance.

    Returns:
        Updated `AgentState` containing mutation receipts and customer confirmation.
    """
    order_svc = order_service or OrderService()
    payment_svc = payment_service or PaymentService()

    entities = getattr(state.route_decision, "entities", None)
    order_id = getattr(entities, "order_id", None) if entities else None
    action_type = getattr(entities, "action_type", None) if entities else None

    # Step 1: Missing Entity ID Guard
    if not order_id:
        state.action_results = {"status": "failed", "reason": "Missing order_id"}
        state.final_response = (
            "To process your request, please provide the specific order ID (e.g. ORD-1234) "
            "you would like to modify."
        )
        state.clarification_needed = True
        return state

    try:
        # Action 1: Request Refund
        if action_type == "request_refund":
            try:
                order = order_svc.get_order_by_id(order_id)
                payments = payment_svc.get_payments_by_order_id(order_id)

                if not payments:
                    state.action_results = {
                        "status": "failed",
                        "reason": "No payments found for order",
                        "order_id": order_id,
                    }
                    state.final_response = (
                        f"No completed payment record was found for order {order_id} to process a refund."
                    )
                    state.is_escalated = True
                    return state

                refunded_ids = []
                for p in payments:
                    if p.status != PaymentStatus.REFUNDED.value:
                        payment_svc.update_payment_status(
                            p.payment_id,
                            PaymentUpdate(status=PaymentStatus.REFUNDED.value),
                        )
                        refunded_ids.append(p.payment_id)

                state.action_results = {
                    "status": "success",
                    "action": "request_refund",
                    "order_id": order_id,
                    "refunded_payments": refunded_ids,
                }
                state.final_response = (
                    f"A refund request for order {order_id} has been processed successfully."
                )
                return state

            except ResourceNotFoundError:
                state.action_results = {
                    "status": "failed",
                    "reason": "Order not found",
                    "order_id": order_id,
                }
                state.final_response = f"Cannot process refund: Order '{order_id}' does not exist."
                state.clarification_needed = True
                return state

        # Action 2: Cancel Order (default mutation)
        else:
            try:
                order = order_svc.get_order_by_id(order_id)

                # Domain Invariant Check: Already Cancelled
                if str(order.status).upper() == OrderStatus.CANCELLED.value:
                    state.action_results = {
                        "status": "failed",
                        "reason": "Order already cancelled",
                        "order_id": order_id,
                    }
                    state.final_response = f"Order {order_id} is already cancelled."
                    return state

                # Domain Invariant Check: Delivered Orders Cannot Be Cancelled
                if str(order.status).upper() == OrderStatus.DELIVERED.value:
                    state.action_results = {
                        "status": "failed",
                        "reason": "Cannot cancel delivered order",
                        "order_id": order_id,
                    }
                    state.final_response = (
                        f"Order {order_id} cannot be cancelled because it has already been delivered. "
                        f"You may request a return or refund instead."
                    )
                    return state

                # Execute Cancellation
                order_svc.update_order_status(order_id, OrderStatus.CANCELLED)
                state.action_results = {
                    "status": "success",
                    "action": "cancel_order",
                    "order_id": order_id,
                    "new_status": "CANCELLED",
                }
                state.final_response = f"Order {order_id} has been successfully cancelled."
                return state

            except ResourceNotFoundError:
                state.action_results = {
                    "status": "failed",
                    "reason": "Order not found",
                    "order_id": order_id,
                }
                state.final_response = f"Cannot process cancellation: Order '{order_id}' does not exist."
                state.clarification_needed = True
                return state

            except InvalidOperationError as exc:
                state.action_results = {
                    "status": "failed",
                    "reason": exc.reason if hasattr(exc, "reason") else str(exc),
                    "order_id": order_id,
                }
                state.final_response = (
                    f"Order {order_id} could not be cancelled: "
                    f"{exc.reason if hasattr(exc, 'reason') else str(exc)}"
                )
                return state

    except Exception as exc:
        logger.error("Error during action_engine_node execution: %s", exc)
        state.action_results = {"status": "error", "error": str(exc)}
        state.final_response = (
            "We encountered an issue processing your request. "
            "Your inquiry has been escalated to a support representative."
        )
        state.is_escalated = True

    return state


# -----------------------------------------------------------------------------
# 4. Human Escalation Execution Node
# -----------------------------------------------------------------------------

def escalation_node(
    state: AgentState,
    ticket_service: TicketService | None = None,
) -> AgentState:
    """Escalates conversation to human support specialist with dispatch metadata.

    WHAT:
        Flags `state.is_escalated = True` and prepares human handoff confirmation.

    WHY:
        Ensures out-of-scope, complex, or sensitive inquiries receive human intervention.

    HOW:
        1. Sets `state.is_escalated = True`.
        2. Formats empathetic handoff message in `state.final_response` if unset.
        3. Records escalation dispatch receipt in `state.action_results`.

    Args:
        state: Incoming conversational AgentState.
        ticket_service: Optional injected TicketService instance.

    Returns:
        Updated `AgentState` flagged for human escalation.
    """
    state.is_escalated = True

    if not state.final_response:
        state.final_response = (
            "Your inquiry has been escalated to our human support team. "
            "A specialist has been notified and will assist you shortly."
        )

    escalation_reason = (
        getattr(state.route_decision, "reasoning", None)
        if state.route_decision
        else "Customer requested human specialist assistance."
    )

    state.action_results["escalation_payload"] = {
        "session_id": state.session_id,
        "customer_id": state.customer_id,
        "query": state.current_query,
        "reason": escalation_reason,
        "status": "ESCALATED",
    }

    return state
