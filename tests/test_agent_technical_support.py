"""Unit and integration tests for ResolveX Technical Support Agent (Step 6 — Phase 4).

Verifies:
1. Pydantic models `DiagnosticStep` and `TechnicalIssueReport` validation.
2. `TechnicalSupportAgent`:
   - Diagnostic flow for mobile app crash and bug symptoms.
   - Diagnostic flow for device power failures and hardware symptoms.
   - Error code extraction and targeted diagnostic step generation.
   - Interactive troubleshooting state with `clarification_needed = True`.
   - Resolution detection ("that worked", "fixed it") setting `is_resolved = True`.
   - Failure and replacement detection ("still not working", "cracked screen") triggering `is_escalated = True`.
   - Targeted RAG integration for retrieving technical manual passages.
3. `technical_support_node`:
   - Direct execution node handler over `AgentState`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.agent.nodes import technical_support_node
from Backend.agent.router import ExtractedEntities, IntentType, RouteDecision
from Backend.agent.state import AgentState
from Backend.agent.technical_support import (
    DiagnosticStep,
    TechnicalIssueReport,
    TechnicalSupportAgent,
)
from Backend.rag.reranking import RankedChunk
from Backend.rag.retrieval import RetrievedChunk


# =============================================================================
# 1. Model & Instantiation Tests
# =============================================================================

class TestTechnicalSupportModels:
    """Test suite for DiagnosticStep and TechnicalIssueReport data models."""

    def test_diagnostic_step_model_valid(self):
        step = DiagnosticStep(
            step_number=1,
            instruction="Clear cache and restart the app.",
            expected_outcome="App launches without crashing.",
        )
        assert step.step_number == 1
        assert "Clear cache" in step.instruction
        assert "launches without crashing" in step.expected_outcome

    def test_technical_issue_report_defaults(self):
        report = TechnicalIssueReport(
            device_or_service="Mobile App",
            error_code="ERR-502",
            symptoms=["App crash"],
        )
        assert report.device_or_service == "Mobile App"
        assert report.error_code == "ERR-502"
        assert report.symptoms == ["App crash"]
        assert report.steps_completed == []
        assert report.is_resolved is False


# =============================================================================
# 2. Technical Support Agent Diagnostic Tests
# =============================================================================

class TestTechnicalSupportAgent:
    """Test suite for TechnicalSupportAgent troubleshooting workflows."""

    def test_diagnose_app_crash_symptoms(self):
        agent = TechnicalSupportAgent()
        state = AgentState(
            session_id="sess_tech_1",
            current_query="App keeps crashing on checkout whenever I click pay",
        )

        updated_state = agent.diagnose(query=state.current_query, state=state)

        assert updated_state.clarification_needed is True
        assert updated_state.is_escalated is False
        assert "Mobile App" in updated_state.final_response or "checkout" in updated_state.final_response.lower()
        assert "1." in updated_state.final_response
        assert "2." in updated_state.final_response

        # Check technical report in action_results
        report = updated_state.action_results.get("technical_report")
        assert report is not None
        assert report["is_resolved"] is False
        assert len(updated_state.action_results["diagnostic_steps"]) >= 2

    def test_diagnose_device_wont_turn_on(self):
        agent = TechnicalSupportAgent()
        state = AgentState(
            session_id="sess_tech_2",
            current_query="My device won't turn on and has no power",
        )

        updated_state = agent.diagnose(query=state.current_query, state=state)

        assert updated_state.clarification_needed is True
        assert updated_state.is_escalated is False
        assert "power" in updated_state.final_response.lower()
        assert "outlet" in updated_state.final_response.lower() or "cable" in updated_state.final_response.lower()

        report = updated_state.action_results.get("technical_report")
        assert report is not None
        assert any("power" in s.lower() for s in report["symptoms"])

    def test_diagnose_with_error_code(self):
        agent = TechnicalSupportAgent()
        state = AgentState(
            session_id="sess_tech_3",
            current_query="I am getting error code ERR-502 on my screen",
        )

        updated_state = agent.diagnose(query=state.current_query, state=state)

        assert updated_state.clarification_needed is True
        assert "ERR-502" in updated_state.final_response
        report = updated_state.action_results.get("technical_report")
        assert report["error_code"] == "ERR-502"

    def test_diagnose_user_confirms_resolution(self):
        agent = TechnicalSupportAgent()
        history = [
            {"role": "user", "content": "App is crashing"},
            {"role": "assistant", "content": "1. Clear cache and restart"},
        ]
        state = AgentState(
            session_id="sess_tech_4",
            current_query="That worked! The app is working now, thank you",
            messages=history,
        )

        updated_state = agent.diagnose(query=state.current_query, history=history, state=state)

        assert updated_state.is_escalated is False
        assert updated_state.clarification_needed is False
        assert "resolved" in updated_state.final_response.lower()

        report = updated_state.action_results.get("technical_report")
        assert report["is_resolved"] is True

    def test_diagnose_troubleshooting_failed_triggers_escalation(self):
        agent = TechnicalSupportAgent()
        history = [
            {"role": "user", "content": "Device power issue"},
            {"role": "assistant", "content": "Please check cable and power cycle"},
        ]
        state = AgentState(
            session_id="sess_tech_5",
            current_query="Still not working, tried that already and screen is cracked",
            messages=history,
        )

        updated_state = agent.diagnose(query=state.current_query, history=history, state=state)

        assert updated_state.is_escalated is True
        assert updated_state.clarification_needed is False
        assert "escalated" in updated_state.final_response.lower()
        assert "Senior Technical Support" in updated_state.final_response

        assert "escalation_payload" in updated_state.action_results
        payload = updated_state.action_results["escalation_payload"]
        assert payload["status"] == "ESCALATED"
        assert payload["session_id"] == "sess_tech_5"

    def test_diagnose_with_injected_rag_components(self):
        mock_retriever = MagicMock()
        mock_retriever.retrieve_parallel.return_value = (
            [
                RetrievedChunk(
                    chunk_id="tech_manual_01",
                    document_name="device_manual.pdf",
                    section_title="Reset Procedures",
                    chunk_content="Hold power and volume down for 10 seconds to initiate hard reset.",
                    score=0.91,
                    retrieval_type="dense",
                )
            ],
            [],
        )

        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = [
            RankedChunk(
                chunk_id="tech_manual_01",
                document_name="device_manual.pdf",
                section_title="Reset Procedures",
                chunk_content="Hold power and volume down for 10 seconds to initiate hard reset.",
                score=0.91,
                retrieval_type="hybrid",
                rrf_score=0.016,
                rerank_score=0.91,
                final_rank=1,
            )
        ]

        agent = TechnicalSupportAgent(retriever=mock_retriever, reranker=mock_reranker)
        state = AgentState(
            session_id="sess_tech_rag",
            current_query="How do I reset my smart speaker device?",
        )

        updated_state = agent.diagnose(query=state.current_query, state=state)

        assert len(updated_state.retrieved_chunks) == 1
        assert updated_state.retrieved_chunks[0].chunk_id == "tech_manual_01"
        mock_retriever.retrieve_parallel.assert_called_once()
        mock_reranker.rerank.assert_called_once()


# =============================================================================
# 3. Technical Support Node Tests
# =============================================================================

class TestTechnicalSupportNode:
    """Test suite for technical_support_node function."""

    def test_technical_support_node_execution(self):
        state = AgentState(
            session_id="sess_node_1",
            current_query="Cannot connect to wifi network on my device",
            route_decision=RouteDecision(
                intent=IntentType.TECHNICAL_SUPPORT,
                confidence=0.95,
                entities=ExtractedEntities(),
                reasoning="Wi-Fi connectivity problem",
            ),
        )

        updated_state = technical_support_node(state)

        assert updated_state.clarification_needed is True
        assert updated_state.is_escalated is False
        assert "technical_report" in updated_state.action_results
        assert len(updated_state.action_results["diagnostic_steps"]) > 0
