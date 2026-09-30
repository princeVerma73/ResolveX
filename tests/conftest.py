"""Global pytest fixtures and test lifecycle configurations for ResolveX test suite."""

import pytest
from Backend.core.guardrails import llm_circuit_breaker


@pytest.fixture(autouse=True)
def reset_global_circuit_breaker():
    """Ensures each unit and integration test executes with a clean circuit breaker state."""
    llm_circuit_breaker.reset()
    yield
    llm_circuit_breaker.reset()
