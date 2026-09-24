"""Structured LLM Intent Router and Entity Extractor for ResolveX multi-agent pipeline.

Step 6 — Phase 1: Agent State & Structured LLM Intent Router.

WHAT:
    Classifies incoming customer messages into a strict 4-way Intent taxonomy:
    1. `POLICY_INQUIRY`: Grounded company policy, return terms, FAQs, and guidelines questions.
    2. `DATABASE_LOOKUP`: Read-only operational inquiries (order tracking, payment status, customer data).
    3. `ACTION_EXECUTION`: Mutative transactional requests (cancel order, request refund, update address).
    4. `GENERAL_ESCALATION`: Human supervisor requests, legal threats, or out-of-scope interactions.

WHY:
    - Prevents compute-heavy RAG searches for simple order status checks.
    - Protects the database from direct query load on pure policy questions.
    - Standardizes entity extraction (`order_id`, `email`, `customer_id`, `action_type`) before invoking tools.

HOW:
    - Uses Google GenAI SDK (`google.genai.Client`) with `gemini-1.5-flash` at `temperature=0.0`.
    - Enforces Pydantic structured output mode (`response_schema=RouteDecision`).
    - Implements backoff resilience and heuristic fallback on network dropouts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Load root .env if present
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

DEFAULT_ROUTER_MODEL = os.getenv("ROUTER_MODEL", "gemini-1.5-flash").strip()

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Intent Taxonomy & Entity Extraction Models
# -----------------------------------------------------------------------------

class IntentType(str, Enum):
    """Mutually exclusive 4-way intent classification taxonomy."""

    POLICY_INQUIRY = "POLICY_INQUIRY"
    DATABASE_LOOKUP = "DATABASE_LOOKUP"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    GENERAL_ESCALATION = "GENERAL_ESCALATION"


class ExtractedEntities(BaseModel):
    """Structured container for domain parameters extracted from user query."""

    order_id: str | None = Field(
        default=None, description="Extracted order ID (e.g. 'ORD-8832')"
    )
    customer_id: str | None = Field(
        default=None, description="Extracted customer ID (e.g. 'CUST-001')"
    )
    email: str | None = Field(
        default=None, description="Extracted customer email address"
    )
    ticket_id: str | None = Field(
        default=None, description="Extracted support ticket ID (e.g. 'TCK-1001')"
    )
    policy_topic: str | None = Field(
        default=None, description="Policy category: refund, shipping, cancellation, account, payment"
    )
    action_type: str | None = Field(
        default=None, description="Target action: cancel_order, request_refund, update_address"
    )


class RouteDecision(BaseModel):
    """Structured intent classification and routing payload."""

    intent: IntentType = Field(..., description="Classified 4-way intent")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )
    entities: ExtractedEntities = Field(
        default_factory=ExtractedEntities, description="Extracted domain entities"
    )
    reasoning: str = Field(
        default="", description="Brief diagnostic reasoning for the decision"
    )


# -----------------------------------------------------------------------------
# 2. Structured LLM Intent Router
# -----------------------------------------------------------------------------

class IntentRouter:
    """Enterprise LLM Intent Router using structured Gemini-1.5-Flash outputs.

    WHAT:
        Translates raw customer natural language messages into strongly typed `RouteDecision` objects.

    WHY:
        Guarantees deterministic downstream routing across Policy RAG, Relational Database Lookups,
        Transactional Action Engine, and Human Escalation.

    HOW:
        - Constructs an explicit classification prompt with intent boundaries.
        - Calls `client.models.generate_content` with `temperature=0.0` and `response_schema=RouteDecision`.
        - Validates the output through Pydantic with fallback parsing on edge-case format deviations.
    """

    SYSTEM_INSTRUCTIONS = (
        "You are the ResolveX Central Intent Classification and Entity Extraction Router.\n"
        "Your task is to analyze the user's inquiry and classify it into EXACTLY ONE of the following 4 intents:\n\n"
        "1. POLICY_INQUIRY: General questions about store terms, return policy rules, refund processing timelines, "
        "shipping durations, cancellation rules, payment FAQs, or privacy guidelines.\n"
        "   Examples: 'What is your refund policy?', 'Can I return opened clothes?', 'How long does delivery take?'\n\n"
        "2. DATABASE_LOOKUP: Read-only inquiries asking for specific existing data, such as tracking a specific order ID, "
        "checking payment status for an account, or finding customer records.\n"
        "   Examples: 'Where is my order ORD-8832?', 'Check status for user john@example.com', 'Did payment PAY-101 succeed?'\n\n"
        "3. ACTION_EXECUTION: Explicit requests to mutate state or execute a transaction, such as cancelling an order, "
        "initiating a product return, or updating a delivery address.\n"
        "   Examples: 'Please cancel order ORD-5511 immediately', 'I want to cancel my purchase', 'Refund my order ORD-9921'\n\n"
        "4. GENERAL_ESCALATION: Requests to speak directly with a human representative, supervisor, or CEO, legal threats, "
        "abusive language, or queries completely outside corporate retail operations.\n"
        "   Examples: 'Transfer me to a human', 'I want to talk to your CEO', 'I am suing your company'\n\n"
        "EXTRACTION RULES:\n"
        "- Extract any mentioned order_id (e.g. ORD-1234), email, customer_id, ticket_id, policy_topic, or action_type.\n"
        "- Output strictly adhering to the JSON schema."
    )

    def __init__(
        self,
        genai_client: genai.Client | None = None,
        model_name: str = DEFAULT_ROUTER_MODEL,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
    ) -> None:
        """Initialize the Intent Router.

        Args:
            genai_client: Injected Google GenAI client (lazy loaded if None).
            model_name: Generation model identifier (default: 'gemini-1.5-flash').
            max_retries: Maximum retry attempts for transient API errors.
            base_delay_seconds: Base backoff delay in seconds.
        """
        self._genai_client = genai_client
        self.model_name = model_name
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds

    @property
    def genai_client(self) -> genai.Client:
        """Lazy-loading accessor for the Google GenAI SDK client."""
        if self._genai_client is None:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
            if not api_key:
                raise ValueError(
                    "Missing 'GEMINI_API_KEY'. Please set GEMINI_API_KEY in your root .env file."
                )
            self._genai_client = genai.Client(api_key=api_key)
        return self._genai_client

    def classify_intent(
        self,
        query: str,
        history: Sequence[dict[str, Any]] | None = None,
    ) -> RouteDecision:
        """Classifies the user query into a structured RouteDecision.

        WHAT:
            The primary intent classification endpoint for the ResolveX multi-agent system.

        WHY:
            Ensures deterministic, schema-validated routing across specialized agent sub-graphs.

        HOW:
            1. Pre-validates non-empty input query.
            2. Builds contextual prompt including conversation history turns (if available).
            3. Invokes Gemini-1.5-Flash with `response_mime_type="application/json"` and `response_schema=RouteDecision`.
            4. Validates and parses the JSON output into a `RouteDecision` model.
            5. Gracefully falls back to heuristic extraction on external API errors.

        Args:
            query: User input query string.
            history: Optional list of previous conversation turns `[{"role": "user", "content": "..."}, ...]`.

        Returns:
            `RouteDecision` instance containing intent, confidence, entities, and reasoning.

        Raises:
            ValueError: If query is empty or whitespace-only.
        """
        if not query or not query.strip():
            raise ValueError("Query string for intent classification cannot be empty.")

        clean_query = query.strip()

        # Format conversation history context if provided
        history_str = ""
        if history:
            history_lines = []
            for turn in history[-5:]:  # Include last 5 turns
                role = turn.get("role", "user").upper()
                content = turn.get("content", "")
                history_lines.append(f"{role}: {content}")
            history_str = f"RECENT CONVERSATION HISTORY:\n" + "\n".join(history_lines) + "\n\n"

        prompt = (
            f"{self.SYSTEM_INSTRUCTIONS}\n\n"
            f"{history_str}"
            f"CURRENT USER INQUIRY: {clean_query}\n\n"
            f"CLASSIFY AND EXTRACT JSON:"
        )

        config = types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=RouteDecision,
        )

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )

                raw_text = response.text or ""
                # Strip markdown code blocks if present
                clean_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
                clean_json = re.sub(r"\s*```$", "", clean_json.strip(), flags=re.MULTILINE)

                decision = RouteDecision.model_validate_json(clean_json)
                return decision

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Intent classification attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )

        # Fallback Heuristic Routing on API failure
        logger.error(
            "Intent classification failed after %d retries. Falling back to heuristic classifier. Error: %s",
            self.max_retries,
            last_error,
        )
        return self._heuristic_fallback(clean_query)

    def _heuristic_fallback(self, query: str) -> RouteDecision:
        """Lightweight regex-based fallback classifier when Gemini API is unreachable."""
        lower_q = query.lower()

        # Extract order ID if present (ORD-XXXX)
        order_match = re.search(r"\bORD[-_]?\d+\b", query, re.IGNORECASE)
        order_id = order_match.group(0).upper() if order_match else None

        # Extract email if present
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", query)
        email = email_match.group(0) if email_match else None

        entities = ExtractedEntities(order_id=order_id, email=email)

        # 1. Action Execution keywords
        if any(w in lower_q for w in ["cancel", "refund my", "change address", "return my"]):
            entities.action_type = "cancel_order" if "cancel" in lower_q else "request_refund"
            return RouteDecision(
                intent=IntentType.ACTION_EXECUTION,
                confidence=0.75,
                entities=entities,
                reasoning="Heuristic match: Action mutation keyword detected.",
            )

        # 2. Database Lookup keywords
        if order_id or email or any(w in lower_q for w in ["where is my", "track", "status of order", "my package"]):
            return RouteDecision(
                intent=IntentType.DATABASE_LOOKUP,
                confidence=0.75,
                entities=entities,
                reasoning="Heuristic match: Specific order ID or tracking keyword detected.",
            )

        # 3. Escalation keywords
        if any(w in lower_q for w in ["human", "agent", "ceo", "lawyer", "sue", "manager", "representative"]):
            return RouteDecision(
                intent=IntentType.GENERAL_ESCALATION,
                confidence=0.80,
                entities=entities,
                reasoning="Heuristic match: Escalation keyword detected.",
            )

        # 4. Default: Policy Inquiry
        return RouteDecision(
            intent=IntentType.POLICY_INQUIRY,
            confidence=0.70,
            entities=entities,
            reasoning="Heuristic fallback: Defaulted to policy inquiry.",
        )
