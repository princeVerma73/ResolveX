"""ResolveX Multi-Agent Architecture Package (Step 6).

Provides LangGraph multi-agent state definitions, structured intent classification,
specialized domain sub-agents, and deterministic action tools.
"""

from Backend.agent.graph import SupportAgentOrchestrator
from Backend.agent.nodes import (
    action_engine_node,
    db_lookup_node,
    escalation_node,
    policy_rag_node,
    technical_support_node,
)
from Backend.agent.router import (
    ExtractedEntities,
    IntentRouter,
    IntentType,
    RouteDecision,
)
from Backend.agent.state import AgentState
from Backend.agent.technical_support import (
    DiagnosticStep,
    TechnicalIssueReport,
    TechnicalSupportAgent,
)

__all__ = [
    "AgentState",
    "IntentType",
    "ExtractedEntities",
    "RouteDecision",
    "IntentRouter",
    "DiagnosticStep",
    "TechnicalIssueReport",
    "TechnicalSupportAgent",
    "policy_rag_node",
    "db_lookup_node",
    "action_engine_node",
    "technical_support_node",
    "escalation_node",
    "SupportAgentOrchestrator",
]
