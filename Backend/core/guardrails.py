"""Enterprise Guardrails and Input Sanitization for ResolveX.

Provides:
1. Input sanitization against empty strings, whitespace, and length extremes.
2. System prompt override and prompt injection rejection.
3. Groundedness threshold guardrails.
4. Circuit breaker and deterministic fallback for LLM API dropouts.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Sequence

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 1. Prompt Injection & Jailbreak Detection Patterns
# -----------------------------------------------------------------------------

PROMPT_INJECTION_PATTERNS = [
    # Override / Ignore system instructions
    re.compile(
        r"(?i)\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|system|all)\b.{0,40}\b(instructions|prompts|rules|commands|guidelines|guardrails)\b"
    ),
    # System prompt extraction / leaks
    re.compile(
        r"(?i)\b(reveal|show|print|output|display|repeat|leak|dump)\b.{0,30}\b(system\s+prompt|developer\s+prompt|hidden\s+instructions|initial\s+prompt)\b"
    ),
    # Jailbreak personas (DAN, Developer Mode, etc.)
    re.compile(
        r"(?i)\b(you are now|pretend to be|act as|switch to|enter)\b.{0,30}\b(dan|developer mode|jailbreak|unfiltered|unrestricted|god mode|evil mode)\b"
    ),
    # Guardrail disabling attempts
    re.compile(
        r"(?i)\b(disable|turn off|bypass)\b.{0,30}\b(safety|content filter|guardrails|moderation)\b"
    ),
]

SAFE_INJECTION_REJECTION_MESSAGE = (
    "I cannot fulfill requests that attempt to alter or override my system instructions "
    "or security guidelines. How may I help you with your order, return, or technical support today?"
)

DETERMINISTIC_LLM_FALLBACK_MESSAGE = (
    "Our AI resolution assistant is currently experiencing high demand. "
    "Here are common self-service options: you can track your order using your Order ID "
    "(e.g., ORD-1234), view our 30-day return policy, or be connected directly to a human support specialist."
)


def check_prompt_injection(query: str) -> tuple[bool, str | None]:
    """Inspects the query string for known prompt injection or jailbreak patterns.

    Args:
        query: Raw or stripped user input text.

    Returns:
        tuple (is_injection, rejection_message)
    """
    if not query:
        return False, None

    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(query):
            logger.warning("Prompt injection attempt intercepted: %s", query[:80])
            return True, SAFE_INJECTION_REJECTION_MESSAGE

    return False, None


def validate_and_sanitize_input(query: str) -> tuple[bool, str, str | None]:
    """Validates and sanitizes incoming user input before invoking the agent graph.

    Args:
        query: Incoming raw input query string.

    Returns:
        tuple (is_valid, cleaned_query, error_or_rejection_message)
    """
    if query is None:
        return False, "", "Query string cannot be empty."

    # Strip whitespace and null bytes
    cleaned = query.replace("\x00", "").strip()

    # Empty or pure whitespace check
    if not cleaned:
        return False, "", "Please enter a valid message or question so I can assist you."

    # Guard against prompt injection
    is_injection, rejection_msg = check_prompt_injection(cleaned)
    if is_injection:
        return False, cleaned, rejection_msg

    # Truncate excessively long inputs to prevent DoS (max 2000 chars)
    if len(cleaned) > 2000:
        cleaned = cleaned[:2000].rsplit(" ", 1)[0] + "..."

    return True, cleaned, None


# -----------------------------------------------------------------------------
# 2. Groundedness Verification Guardrail
# -----------------------------------------------------------------------------

GROUNDEDNESS_THRESHOLD = 0.70
RETRIEVAL_SIMILARITY_FLOOR = 0.65


def check_groundedness(score: float, threshold: float = GROUNDEDNESS_THRESHOLD) -> bool:
    """Verifies that the composite or cross-encoder retrieval score exceeds the safety threshold.

    Args:
        score: Relevance or confidence score (0.0 to 1.0).
        threshold: Minimum acceptable groundedness floor (default: 0.70).

    Returns:
        True if the score is sufficient, False otherwise.
    """
    return score >= threshold


# -----------------------------------------------------------------------------
# 3. LLM API Circuit Breaker
# -----------------------------------------------------------------------------

class LLMCircuitBreaker:
    """Lightweight in-memory circuit breaker for external LLM API resilience."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def record_success(self) -> None:
        """Resets the circuit breaker upon successful API interaction."""
        self.reset()

    def reset(self) -> None:
        """Explicitly resets circuit breaker to closed initial state."""
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = 0.0

    def record_failure(self) -> None:
        """Records an API failure and trips the circuit open if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                "LLM Circuit Breaker tripped to OPEN after %d consecutive failures.",
                self.failure_count,
            )

    def is_available(self) -> bool:
        """Checks if the circuit breaker allows requests to pass through."""
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if recovery timeout has elapsed
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("LLM Circuit Breaker entered HALF_OPEN state; testing connection.")
                return True
            return False

        # HALF_OPEN allows a single probe attempt
        return True

    def get_fallback_message(self) -> str:
        """Returns the deterministic fallback message when circuit is OPEN."""
        return DETERMINISTIC_LLM_FALLBACK_MESSAGE


# Singleton circuit breaker instance
llm_circuit_breaker = LLMCircuitBreaker()
