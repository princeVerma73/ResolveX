"""Central StateGraph Multi-Agent Orchestrator for ResolveX.

Step 6 — Phase 3: StateGraph Orchestration & Conditional Execution Pipeline.

WHAT:
    Assembles and compiles the full multi-agent conversational pipeline using LangGraph:
    - `router_node`: Dispatches raw query to `IntentRouter` to obtain structured `RouteDecision`.
    - `route_condition`: Dynamic branching router resolving intent -> target worker node.
    - Worker Nodes: `policy_rag_node`, `db_lookup_node`, `action_engine_node`, `escalation_node`.
    - Terminal Edge: All worker branches converge deterministically to LangGraph `END`.
    - Message History Synchronization: Appends turns to `state.messages` maintaining conversational continuity.

WHY:
    - Provides a single, unified entry point (`orchestrator.run(...)` and `orchestrator.arun(...)`) for FastAPI and WebSockets.
    - Eliminates fragile nested condition blocks and isolates agent handoffs into a declarative graph topology.
    - Ensures full session auditability by propagating typed `AgentState` throughout all nodes.

HOW:
    - Builds `StateGraph(AgentState)` using `langgraph.graph.StateGraph` and `END`.
    - Adds node functions wrapping `nodes.py` with injected or default service/RAG dependencies.
    - Adds conditional edges based on `state.route_decision.intent`.
    - Compiles into an executable graph and exposes synchronous and asynchronous execution APIs.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from langgraph.graph import END, StateGraph

from Backend.agent.nodes import (
    action_engine_node,
    db_lookup_node,
    escalation_node,
    policy_rag_node,
)
from Backend.agent.router import IntentRouter, IntentType
from Backend.agent.state import AgentState
from Backend.rag.generation import ResolutionGenerator
from Backend.rag.reranking import CrossEncoderReranker
from Backend.rag.retrieval import HybridRetriever
from Backend.services.customer_service import CustomerService
from Backend.services.order_service import OrderService
from Backend.services.payment_service import PaymentService
from Backend.services.ticket_service import TicketService

logger = logging.getLogger(__name__)


class SupportAgentOrchestrator:
    """Enterprise multi-agent orchestrator compiling a LangGraph StateGraph pipeline.

    WHAT:
        Coordinates intent classification, dynamic worker branching, domain service lookups,
        RAG passage generation, action state mutations, and multi-turn conversational history.

    WHY:
        Standardizes end-to-end multi-agent execution behind a clean, testable interface.

    HOW:
        - Compiles LangGraph StateGraph on initialization.
        - Synchronously executes via `.run()` or asynchronously via `.arun()`.
    """

    def __init__(
        self,
        router: IntentRouter | None = None,
        retriever: HybridRetriever | None = None,
        reranker: CrossEncoderReranker | None = None,
        generator: ResolutionGenerator | None = None,
        order_service: OrderService | None = None,
        ticket_service: TicketService | None = None,
        customer_service: CustomerService | None = None,
        payment_service: PaymentService | None = None,
    ) -> None:
        """Initialize the Support Agent Orchestrator with optional dependency injection.

        Args:
            router: Intent classification router (default: IntentRouter()).
            retriever: RAG hybrid retriever (default: None, lazy in node).
            reranker: FlashRank cross-encoder reranker (default: None, lazy in node).
            generator: Grounded generation engine (default: None, lazy in node).
            order_service: Relational order service (default: None, lazy in node).
            ticket_service: Relational ticket service (default: None, lazy in node).
            customer_service: Relational customer service (default: None, lazy in node).
            payment_service: Relational payment service (default: None, lazy in node).
        """
        self.router = router or IntentRouter()
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator
        self.order_service = order_service
        self.ticket_service = ticket_service
        self.customer_service = customer_service
        self.payment_service = payment_service

        self.workflow = self._build_graph()
        self.compiled_graph = self.workflow.compile()

    # -------------------------------------------------------------------------
    # Graph Construction & Node Adapters
    # -------------------------------------------------------------------------

    def _router_node(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Executes intent classification and entity extraction if not already set."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        if agent_state.route_decision is None:
            decision = self.router.classify_intent(
                query=agent_state.current_query,
                history=agent_state.messages,
            )
            agent_state.route_decision = decision
        return agent_state

    def _policy_rag_node(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Node adapter for Policy RAG worker."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        return policy_rag_node(
            state=agent_state,
            retriever=self.retriever,
            reranker=self.reranker,
            generator=self.generator,
        )

    def _db_lookup_node(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Node adapter for DB Lookup worker."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        return db_lookup_node(
            state=agent_state,
            order_service=self.order_service,
            ticket_service=self.ticket_service,
            customer_service=self.customer_service,
            payment_service=self.payment_service,
        )

    def _action_engine_node(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Node adapter for Action Engine worker."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        return action_engine_node(
            state=agent_state,
            order_service=self.order_service,
            payment_service=self.payment_service,
            ticket_service=self.ticket_service,
        )

    def _escalation_node(self, state: AgentState | dict[str, Any]) -> AgentState:
        """Node adapter for Human Escalation worker."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        return escalation_node(
            state=agent_state,
            ticket_service=self.ticket_service,
        )

    @staticmethod
    def _route_intent(state: AgentState | dict[str, Any]) -> str:
        """Conditional dynamic routing function mapping intent enum to graph worker node."""
        agent_state = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        decision = agent_state.route_decision
        if not decision or not hasattr(decision, "intent"):
            return "escalation"

        intent = decision.intent
        if intent == IntentType.POLICY_INQUIRY:
            return "policy_rag"
        elif intent == IntentType.DATABASE_LOOKUP:
            return "db_lookup"
        elif intent == IntentType.ACTION_EXECUTION:
            return "action_engine"
        elif intent == IntentType.GENERAL_ESCALATION:
            return "escalation"
        return "escalation"

    def _build_graph(self) -> StateGraph:
        """Assembles the LangGraph StateGraph topology."""
        workflow = StateGraph(AgentState)

        # 1. Add Execution Nodes
        workflow.add_node("router", self._router_node)
        workflow.add_node("policy_rag", self._policy_rag_node)
        workflow.add_node("db_lookup", self._db_lookup_node)
        workflow.add_node("action_engine", self._action_engine_node)
        workflow.add_node("escalation", self._escalation_node)

        # 2. Set Entry Point
        workflow.set_entry_point("router")

        # 3. Add Conditional Branching Edges
        workflow.add_conditional_edges(
            "router",
            self._route_intent,
            {
                "policy_rag": "policy_rag",
                "db_lookup": "db_lookup",
                "action_engine": "action_engine",
                "escalation": "escalation",
            },
        )

        # 4. Terminal Convergence to END
        workflow.add_edge("policy_rag", END)
        workflow.add_edge("db_lookup", END)
        workflow.add_edge("action_engine", END)
        workflow.add_edge("escalation", END)

        return workflow

    # -------------------------------------------------------------------------
    # Public Execution Endpoints
    # -------------------------------------------------------------------------

    def run(
        self,
        query: str,
        session_id: str | None = None,
        customer_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        initial_state: AgentState | None = None,
    ) -> AgentState:
        """Executes a single synchronous multi-agent interaction turn.

        Args:
            query: Customer input message string.
            session_id: Unique chat session identifier (auto-generated if None).
            customer_id: Customer identifier if authenticated.
            history: Previous conversation turns `[{"role": "user", "content": "..."}, ...]`.
            initial_state: Optional pre-constructed AgentState.

        Returns:
            Fully populated and resolved `AgentState`.
        """
        clean_query = query.strip()
        sess_id = session_id or (
            initial_state.session_id if initial_state else f"sess_{uuid.uuid4().hex[:10]}"
        )
        cust_id = customer_id or (initial_state.customer_id if initial_state else None)
        messages = list(history or (initial_state.messages if initial_state else []))

        state = initial_state or AgentState(
            session_id=sess_id,
            customer_id=cust_id,
            messages=messages,
            current_query=clean_query,
        )

        if not state.current_query:
            state.current_query = clean_query

        output_raw = self.compiled_graph.invoke(state)
        output_state = (
            output_raw if isinstance(output_raw, AgentState) else AgentState.model_validate(output_raw)
        )

        # Append turn to conversational message history
        output_state.messages.append({"role": "user", "content": clean_query})
        if output_state.final_response:
            output_state.messages.append(
                {"role": "assistant", "content": output_state.final_response}
            )

        return output_state

    async def arun(
        self,
        query: str,
        session_id: str | None = None,
        customer_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        initial_state: AgentState | None = None,
    ) -> AgentState:
        """Executes a single asynchronous multi-agent interaction turn.

        Args:
            query: Customer input message string.
            session_id: Unique chat session identifier (auto-generated if None).
            customer_id: Customer identifier if authenticated.
            history: Previous conversation turns.
            initial_state: Optional pre-constructed AgentState.

        Returns:
            Fully populated and resolved `AgentState`.
        """
        clean_query = query.strip()
        sess_id = session_id or (
            initial_state.session_id if initial_state else f"sess_{uuid.uuid4().hex[:10]}"
        )
        cust_id = customer_id or (initial_state.customer_id if initial_state else None)
        messages = list(history or (initial_state.messages if initial_state else []))

        state = initial_state or AgentState(
            session_id=sess_id,
            customer_id=cust_id,
            messages=messages,
            current_query=clean_query,
        )

        if not state.current_query:
            state.current_query = clean_query

        output_raw = await self.compiled_graph.ainvoke(state)
        output_state = (
            output_raw if isinstance(output_raw, AgentState) else AgentState.model_validate(output_raw)
        )

        # Append turn to conversational message history
        output_state.messages.append({"role": "user", "content": clean_query})
        if output_state.final_response:
            output_state.messages.append(
                {"role": "assistant", "content": output_state.final_response}
            )

        return output_state
