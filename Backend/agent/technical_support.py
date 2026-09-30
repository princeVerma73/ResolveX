"""Dedicated Technical Support Sub-Agent for ResolveX multi-agent architecture.

Step 6 — Phase 4: Implementation of Dedicated Technical Support Agent & Sub-Graphs.

WHAT:
    Implements the `TechnicalSupportAgent` responsible for interactive multi-step troubleshooting,
    symptom intake, device/service diagnostics, error-code lookup, and guided remediation flows.

WHY:
    - Technical issues (device failure, app crashes, bug reports, sync errors) require stateful,
      multi-step diagnostic loops rather than single-turn static retrieval or read-only DB lookups.
    - Prevents unnecessary human escalation by walking customers through deterministic troubleshooting
      decision trees while preserving context in `AgentState`.
    - Coordinates targeted knowledge base lookup for hardware/software manuals and guides.

HOW:
    - Defines strongly typed Pydantic models: `DiagnosticStep` and `TechnicalIssueReport`.
    - Evaluates reported symptoms, error codes, and hardware/service platforms.
    - Tracks completed diagnostic steps and evaluates user responses (resolved vs. failed vs. in-progress).
    - Sets `clarification_needed = True` during interactive diagnostic steps awaiting customer verification.
    - Sets `is_escalated = True` if diagnostics fail or physical hardware repair/replacement is needed.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import BaseModel, Field

from Backend.agent.state import AgentState
from Backend.rag.generation import ResolutionGenerator
from Backend.rag.reranking import CrossEncoderReranker, reciprocal_rank_fusion
from Backend.rag.retrieval import HybridRetriever

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Pydantic Models for Technical Diagnostics
# -----------------------------------------------------------------------------

class DiagnosticStep(BaseModel):
    """Structured representation of a single technical diagnostic troubleshooting step."""

    step_number: int = Field(..., description="Sequential step number (1-indexed)")
    instruction: str = Field(..., description="Actionable instruction for the user to perform")
    expected_outcome: str = Field(..., description="Expected diagnostic signal or verification check")


class TechnicalIssueReport(BaseModel):
    """Comprehensive diagnostic tracking report for a technical support session."""

    device_or_service: str = Field(
        default="General System",
        description="Identified device, operating system, or application service",
    )
    error_code: str | None = Field(
        default=None,
        description="Detected system or application error code (e.g. 'ERR-502', 'E101')",
    )
    symptoms: list[str] = Field(
        default_factory=list,
        description="List of observed symptoms (e.g. 'app crash', 'device won't turn on')",
    )
    steps_completed: list[str] = Field(
        default_factory=list,
        description="Diagnostic steps already attempted by the customer",
    )
    is_resolved: bool = Field(
        default=False,
        description="Flag indicating if the technical issue has been confirmed resolved",
    )


# -----------------------------------------------------------------------------
# 2. Technical Support Sub-Agent
# -----------------------------------------------------------------------------

class TechnicalSupportAgent:
    """Specialized technical support worker sub-agent.

    WHAT:
        Analyzes technical issues, formulates step-by-step diagnostic workflows,
        integrates with policy/technical manuals via RAG, and manages resolution or escalation.

    WHY:
        Isolates technical troubleshooting logic from transactional order management
        and general store policy Q&A.

    HOW:
        - Parses query and conversation history for error codes, symptoms, and devices.
        - Checks for user confirmation signals ("it worked", "fixed", "still broken").
        - Emits structured `DiagnosticStep` recommendations with verification prompts.
        - Updates `AgentState.action_results` with `technical_report` and diagnostic logs.
    """

    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        reranker: CrossEncoderReranker | None = None,
        generator: ResolutionGenerator | None = None,
    ) -> None:
        """Initialize Technical Support Agent with optional RAG components.

        Args:
            retriever: Optional hybrid retriever for searching technical manuals.
            reranker: Optional cross-encoder reranker for ranking diagnostic passages.
            generator: Optional resolution generator.
        """
        self.retriever = retriever
        self.reranker = reranker
        self.generator = generator

    def diagnose(
        self,
        query: str,
        history: Sequence[dict[str, Any]] | None = None,
        state: AgentState | None = None,
    ) -> AgentState:
        """Runs the diagnostic triage and troubleshooting loop.

        WHAT:
            Primary entry point for technical support processing in ResolveX.

        WHY:
            Transforms user error reports into structured troubleshooting steps
            or escalates irrecoverable hardware/software failures.

        HOW:
            1. Hydrates or initializes `AgentState`.
            2. Detects resolution signals ("it worked", "issue fixed").
            3. Detects failure or replacement signals ("still doesn't work", "cracked screen").
            4. Extracts device/service and error codes via regex.
            5. Optionally retrieves relevant troubleshooting passages via RAG.
            6. Constructs ordered `DiagnosticStep` list and updates `state`.

        Args:
            query: Current user inquiry or diagnostic response.
            history: Optional conversation history turns.
            state: Optional existing AgentState to mutate.

        Returns:
            Updated `AgentState` with diagnostic recommendations or escalation status.
        """
        clean_query = query.strip()
        hist = list(history or [])

        # Hydrate state if not passed
        current_state = state or AgentState(
            session_id="tech_session",
            current_query=clean_query,
            messages=hist,
        )

        lower_query = clean_query.lower()
        prior_context = " ".join([m.get("content", "").lower() for m in hist[-4:]]) if hist else ""
        combined_text = f"{prior_context} {lower_query}".strip()

        # Step 1: Detect Issue Resolution Signals
        if self._is_resolution_confirmed(lower_query):
            current_state.is_escalated = False
            current_state.clarification_needed = False
            current_state.final_response = (
                "Excellent! I am glad to hear the issue has been resolved. "
                "If you experience any other technical difficulties or have further questions, "
                "please feel free to reach out anytime."
            )
            report = TechnicalIssueReport(
                device_or_service=self._extract_device(combined_text),
                error_code=self._extract_error_code(combined_text),
                symptoms=["issue previously reported"],
                steps_completed=["Troubleshooting completed successfully"],
                is_resolved=True,
            )
            current_state.action_results["technical_report"] = report.model_dump()
            return current_state

        # Step 2: Detect Irrecoverable Failure or Replacement Signals
        if self._requires_immediate_escalation(lower_query, prior_context):
            current_state.is_escalated = True
            current_state.clarification_needed = False
            error_code = self._extract_error_code(combined_text)
            device = self._extract_device(combined_text)
            err_str = f" regarding error code '{error_code}'" if error_code else ""

            current_state.final_response = (
                f"Because the diagnostic troubleshooting steps did not resolve the issue with your {device}{err_str}, "
                "or physical hardware service/replacement is required, I have escalated your case to our "
                "Senior Technical Support Engineering team. A specialist has received your diagnostic history "
                "and will contact you shortly."
            )
            report = TechnicalIssueReport(
                device_or_service=device,
                error_code=error_code,
                symptoms=self._extract_symptoms(combined_text),
                steps_completed=["Standard diagnostic steps exhausted or hardware failure detected"],
                is_resolved=False,
            )
            current_state.action_results["technical_report"] = report.model_dump()
            current_state.action_results["escalation_payload"] = {
                "session_id": current_state.session_id,
                "customer_id": current_state.customer_id,
                "device_or_service": device,
                "error_code": error_code,
                "reason": "Technical troubleshooting exhausted or hardware failure detected.",
                "status": "ESCALATED",
            }
            return current_state

        # Step 3: Extract Domain Information (Device, Error Code, Symptoms)
        device = self._extract_device(combined_text)
        error_code = self._extract_error_code(combined_text)
        symptoms = self._extract_symptoms(combined_text)

        # Step 4: Optional Knowledge Base / RAG Lookup for Technical Manuals
        if self.retriever:
            try:
                dense, sparse = self.retriever.retrieve_parallel(clean_query, limit=5)
                fused = reciprocal_rank_fusion(dense, sparse, top_n=5)
                if self.reranker and fused:
                    ranked = self.reranker.rerank(clean_query, fused, top_k=2)
                    current_state.retrieved_chunks = list(ranked)
            except Exception as exc:
                logger.warning("RAG retrieval within TechnicalSupportAgent failed: %s", exc)

        # Step 5: Formulate Diagnostic Steps & Decision Tree
        steps = self._build_diagnostic_steps(device, error_code, symptoms, lower_query)

        # Step 6: Construct Structured Response
        steps_text = "\n".join(
            [f"{s.step_number}. **{s.instruction}**\n   - *Expected*: {s.expected_outcome}" for s in steps]
        )

        header = f"I've initiated a technical diagnostic session for your **{device}**"
        if error_code:
            header += f" (Error Code: `{error_code}`)"
        header += ".\n\nPlease follow these guided troubleshooting steps:"

        current_state.final_response = (
            f"{header}\n\n"
            f"{steps_text}\n\n"
            "Please perform **Step 1** first and let me know the result: Did it resolve the issue, "
            "or are you still experiencing problems?"
        )
        current_state.clarification_needed = True
        current_state.is_escalated = False

        report = TechnicalIssueReport(
            device_or_service=device,
            error_code=error_code,
            symptoms=symptoms,
            steps_completed=[],
            is_resolved=False,
        )
        current_state.action_results["technical_report"] = report.model_dump()
        current_state.action_results["diagnostic_steps"] = [s.model_dump() for s in steps]

        return current_state

    # -------------------------------------------------------------------------
    # Helper Analyzers & Decision Logic
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_resolution_confirmed(query: str) -> bool:
        """Checks if user indicates the troubleshooting step worked."""
        resolved_patterns = [
            r"\b(it\s+worked|that\s+worked|fixed|it\s+fixed\s+it|working\s+now|works\s+now)\b",
            r"\b(resolved|problem\s+solved|issue\s+resolved|all\s+good\s+now)\b",
            r"\b(thank\s+you\s+it\s+works|it\'?s\s+fine\s+now)\b",
        ]
        return any(re.search(pat, query, re.IGNORECASE) for pat in resolved_patterns)

    @staticmethod
    def _requires_immediate_escalation(query: str, prior_context: str) -> bool:
        """Checks if user indicates troubleshooting failed, hardware damage, or escalation."""
        failure_patterns = [
            r"\b(still\s+(not\s+working|broken|crashing|failing|down|won\'?t\s+turn\s+on))\b",
            r"\b(tried\s+that\s+already|doesn\'?t\s+help|didn\'?t\s+work|tried\s+all\s+steps)\b",
            r"\b(cracked\s+screen|hardware\s+(damage|failure|defect)|smoke|burnt|broken\s+port)\b",
            r"\b(needs?\s+replacement|replace\s+my\s+device|hardware\s+replacement)\b",
            r"\b(fatal\s+error|unrecoverable|blue\s+screen\s+of\s+death|bsod)\b",
        ]
        if any(re.search(pat, query, re.IGNORECASE) for pat in failure_patterns):
            return True

        # If previous context already gave diagnostic steps and user now says "no" / "failed" / "didn't work"
        if prior_context and any(w in query for w in ["still nothing", "no change", "failed", "didn't help"]):
            return True

        return False

    @staticmethod
    def _extract_device(text: str) -> str:
        """Identifies target device, application platform, or hardware product."""
        device_map = [
            (r"\b(mobile\s+app|android|iphone|ios|app\b)", "Mobile App"),
            (r"\b(website|browser|portal|checkout|webpage)\b", "Web Platform"),
            (r"\b(smart\s+speaker|speaker|audio)\b", "Smart Speaker Device"),
            (r"\b(tablet|ipad|display|screen)\b", "Tablet / Display"),
            (r"\b(router|wifi|network|gateway)\b", "Network Router / Modem"),
            (r"\b(smart\s+watch|wearable)\b", "Smart Wearable"),
            (r"\b(printer|scanner)\b", "Printer / Scanner"),
            (r"\b(smart\s+plug|iot|sensor)\b", "IoT Smart Device"),
            (r"\b(device|hardware)\b", "Hardware Device"),
        ]
        for pattern, label in device_map:
            if re.search(pattern, text, re.IGNORECASE):
                return label
        return "Application / Hardware Service"

    @staticmethod
    def _extract_error_code(text: str) -> str | None:
        """Extracts standard error codes (e.g. ERR-502, ERROR 404, E102, #500)."""
        match = re.search(r"\b(?:ERR[-_]?\d+|ERROR[-_ ]?\d+|E[-_]?\d{3,4}|HTTP[-_ ]?\d{3})\b", text, re.IGNORECASE)
        if match:
            return match.group(0).upper().replace(" ", "-")
        return None

    @staticmethod
    def _extract_symptoms(text: str) -> list[str]:
        """Extracts observed symptoms from user query."""
        symptoms = []
        checks = [
            (r"\b(crash(es|ing)?|freez(es|ing)?)\b", "Application crash or freeze"),
            (r"\b(won\'?t\s+turn\s+on|no\s+power|dead)\b", "Power failure / Won't power on"),
            (r"\b(slow|lag|unresponsive)\b", "Performance degradation or lag"),
            (r"\b(cannot\s+connect|disconnect(ed|ing)?|offline|wifi)\b", "Connectivity or network dropout"),
            (r"\b(blank\s+screen|black\s+screen)\b", "Display failure / Blank screen"),
            (r"\b(checkout|payment)\s+error\b", "Checkout transaction failure"),
        ]
        for pattern, label in checks:
            if re.search(pattern, text, re.IGNORECASE):
                symptoms.append(label)
        if not symptoms:
            symptoms.append("Unspecified technical malfunction")
        return symptoms

    def _build_diagnostic_steps(
        self,
        device: str,
        error_code: str | None,
        symptoms: list[str],
        query: str,
    ) -> list[DiagnosticStep]:
        """Generates ordered diagnostic steps tailored to the issue profile."""
        steps: list[DiagnosticStep] = []

        # Branch 1: App crash or web platform issue
        if "Mobile App" in device or "Web" in device or any("crash" in s.lower() for s in symptoms):
            steps.append(
                DiagnosticStep(
                    step_number=1,
                    instruction="Force close the application completely, clear the application cache/cookies, and relaunch.",
                    expected_outcome="The app starts with a fresh session without immediate crash.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=2,
                    instruction="Check your device app store for any pending updates and install the latest patch release.",
                    expected_outcome="The app runs on the latest supported version.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=3,
                    instruction="Uninstall the application, restart your device, and perform a clean reinstallation.",
                    expected_outcome="Corrupted local cache files are purged and functionality is restored.",
                )
            )
            return steps

        # Branch 2: Power / Device won't turn on
        if any("power" in s.lower() for s in symptoms) or "turn on" in query:
            steps.append(
                DiagnosticStep(
                    step_number=1,
                    instruction="Verify that the power cable is securely connected to both the device and a working wall outlet.",
                    expected_outcome="Power indicator LED illuminates or flashes.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=2,
                    instruction="Perform a hard power cycle: Unplug the device, press and hold the power button for 15 seconds, then reconnect power.",
                    expected_outcome="Residual capacitance is cleared and device reboots.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=3,
                    instruction="Try connecting the device using an alternate power adapter or certified charging cable.",
                    expected_outcome="Verifies whether the failure is isolated to the power supply accessory.",
                )
            )
            return steps

        # Branch 3: Network / Connectivity issue
        if any("connect" in s.lower() for s in symptoms):
            steps.append(
                DiagnosticStep(
                    step_number=1,
                    instruction="Toggle Airplane Mode or Wi-Fi off for 10 seconds, then reconnect to your 2.4GHz / 5GHz network.",
                    expected_outcome="Device successfully negotiates a fresh local IP address.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=2,
                    instruction="Restart your internet router/modem by power-cycling for 30 seconds.",
                    expected_outcome="Network connectivity to upstream ISP is re-established.",
                )
            )
            steps.append(
                DiagnosticStep(
                    step_number=3,
                    instruction="Forget the Wi-Fi network on your device and reconnect with your security passphrase.",
                    expected_outcome="Fresh cryptographic handshake resolves authentication mismatches.",
                )
            )
            return steps

        # Branch 4: General Technical / Error Code Default
        steps.append(
            DiagnosticStep(
                step_number=1,
                instruction="Restart the device or service and retry the action that triggered the error.",
                expected_outcome="Transient process locks or memory leaks are cleared.",
            )
        )
        steps.append(
            DiagnosticStep(
                step_number=2,
                instruction="Verify your internet connection and check if any system software updates are available.",
                expected_outcome="System components are up to date and connected to cloud services.",
            )
        )
        steps.append(
            DiagnosticStep(
                step_number=3,
                instruction="Reset system configurations to factory defaults if issue persists.",
                expected_outcome="Restores clean out-of-the-box configuration state.",
            )
        )
        return steps
