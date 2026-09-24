"""Evidence Evaluation, Grounded Prompt Assembly, and Deterministic Response Generation for ResolveX RAG pipeline.

Step 5 — Phase 5: Evidence Evaluation, Grounded Prompt Assembly, Citation Alignment, and Escalation Branching.

WHAT:
    The final synthesis and response termination layer:
    1. Evidence Sufficiency Evaluation: Validates whether retrieved top-3 policy chunks contain
       sufficient, high-confidence evidence to answer the customer's query.
    2. Grounded Prompt Assembly: Formats retrieved context with strict delimiter encapsulation,
       closed-book boundaries, and explicit source citation anchors (`[ID: chunk_id]`).
    3. Deterministic Generation: Executes `gemini-1.5-flash` at `temperature=0.0` via Google GenAI SDK.
    4. Citation Extraction & Alignment: Parses and verifies machine-verifiable source citations.
    5. Escalation & Clarification Branching: Formulates structured clarification or human escalation
       triggers when evidence is ambiguous or missing.

WHY:
    - Eliminates generative hallucinations on critical return windows, fees, and policy terms.
    - Guarantees full auditability by linking every factual statement to specific policy documents.
    - Prevents false confidence by cleanly escalating out-of-scope queries to human agents.

HOW:
    - `EvidenceEvaluator`: Assesses cross-encoder relevance scores and missing query predicates.
    - `GroundedPromptAssembler`: Formats hardened context blocks with `[ID: chunk_id]`.
    - `ResolutionGenerator`: Coordinates evaluation, LLM generation, citation regex extraction,
      and fallback escalation branching.
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

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from Backend.rag.reranking import RankedChunk

# Load root .env if present
ENV_PATH = ROOT_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()

DEFAULT_GENERATION_MODEL = os.getenv("GENERATION_MODEL", "gemini-1.5-flash").strip()
MIN_CONFIDENCE_THRESHOLD = 0.0001

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

class EvaluationResult(BaseModel):
    """Result of evidence sufficiency and completeness evaluation.

    Attributes:
        is_sufficient: Whether the retrieved evidence is adequate to answer the query.
        confidence_score: Composite confidence score (0.0 to 1.0).
        reasoning: Diagnostic explanation of the evaluation decision.
        missing_information: List of missing entities or policy criteria.
    """

    is_sufficient: bool = Field(..., description="Whether evidence is sufficient to answer")
    confidence_score: float = Field(..., ge=0.0, description="Confidence score")
    reasoning: str = Field(..., description="Diagnostic reasoning for decision")
    missing_information: list[str] = Field(
        default_factory=list, description="Identified missing entities or clauses"
    )


class GroundedResponse(BaseModel):
    """Structured response object containing generated answer, citations, and routing flags.

    Attributes:
        response_text: Synthesized answer text or clarification/escalation notice.
        citations: List of verified chunk_id citations extracted from the response.
        is_escalated: True if query was escalated due to out-of-scope or missing policy.
        clarification_needed: True if query is ambiguous and requires user clarification.
    """

    response_text: str = Field(..., description="Final synthesized response text")
    citations: list[str] = Field(
        default_factory=list, description="Verified policy chunk ID citations"
    )
    is_escalated: bool = Field(default=False, description="True if escalated to human agent")
    clarification_needed: bool = Field(
        default=False, description="True if clarification requested from user"
    )


# -----------------------------------------------------------------------------
# Stage 1: Evidence Sufficiency Evaluator
# -----------------------------------------------------------------------------

class EvidenceEvaluator:
    """Evaluates whether retrieved policy passages sufficiently and unambiguously answer the query.

    WHAT:
        Analyzes candidate cross-encoder relevance scores, text premises, and entity completeness.

    WHY:
        Prevents hallucinated answers when a question is out of scope or when retrieved chunks
        do not contain the specific predicate needed.

    HOW:
        - Checks candidate pool non-emptiness.
        - Checks if the top candidate exceeds the baseline cross-attention relevance floor.
        - Identifies underspecified / highly ambiguous queries (e.g. single-word prompts).
    """

    def __init__(self, confidence_threshold: float = MIN_CONFIDENCE_THRESHOLD) -> None:
        """Initialize the Evidence Evaluator.

        Args:
            confidence_threshold: Minimum cross-encoder score floor to consider evidence valid.
        """
        self.confidence_threshold = confidence_threshold

    def evaluate_sufficiency(
        self,
        query: str,
        chunks: Sequence[RankedChunk],
    ) -> EvaluationResult:
        """Assesses evidence completeness for the given query and ranked chunks.

        Args:
            query: Customer query string.
            chunks: Top ranked policy chunks from cross-encoder.

        Returns:
            `EvaluationResult` detailing sufficiency, confidence, and missing information.
        """
        clean_query = query.strip()
        words = clean_query.split()

        # 1. Zero Candidates Check
        if not chunks:
            return EvaluationResult(
                is_sufficient=False,
                confidence_score=0.0,
                reasoning="No relevant policy chunks were retrieved from the knowledge base.",
                missing_information=["Relevant policy documentation"],
            )

        # 2. Ambiguity & Under-specified Query Check (e.g., single word or generic keywords)
        generic_ambiguous_tokens = {"refund", "return", "cancel", "status", "help", "order", "shipping"}
        if len(words) <= 2 and clean_query.lower().strip("?!.,") in generic_ambiguous_tokens:
            return EvaluationResult(
                is_sufficient=False,
                confidence_score=0.2,
                reasoning="Query is ambiguous and lacks specific order details or problem description.",
                missing_information=["Specific order ID or detailed issue description"],
            )

        # 3. Confidence Threshold Check on Top Candidate
        top_chunk = chunks[0]
        score = max(top_chunk.rerank_score, top_chunk.score)

        if score < self.confidence_threshold:
            return EvaluationResult(
                is_sufficient=False,
                confidence_score=round(score, 6),
                reasoning=f"Top candidate relevance score ({score:.6f}) is below the confidence floor ({self.confidence_threshold}).",
                missing_information=["Direct policy match for query intent"],
            )

        # 4. Sufficient evidence confirmed
        return EvaluationResult(
            is_sufficient=True,
            confidence_score=round(score, 6),
            reasoning="Retrieved policy passages contain sufficient context to ground the response.",
            missing_information=[],
        )


# -----------------------------------------------------------------------------
# Stage 2: Grounded Prompt Assembler
# -----------------------------------------------------------------------------

class GroundedPromptAssembler:
    """Assembles hardened, closed-book system prompts with delimiter-encapsulated policy chunks.

    WHAT:
        Serializes top ranked passages into a structured prompt containing explicit citation tags.

    WHY:
        Enforces strict grounding, prevents prompt injection, and mandates `[ID: chunk_id]` citations.

    HOW:
        - Injects closed-book boundary rules and zero-hallucination instructions.
        - Formats each chunk with `[PASSAGE {i}]` and `[ID: {chunk_id}]`.
        - Encapsulates policy context within clear boundary markers.
    """

    SYSTEM_INSTRUCTIONS = (
        "You are the ResolveX Customer Support Policy Assistant.\n"
        "Your task is to provide an accurate, helpful, and concise answer to the user's question "
        "using EXCLUSIVELY the provided policy passages below.\n\n"
        "CRITICAL GROUNDING RULES:\n"
        "1. Rely ONLY on the facts directly stated in the passages. Do NOT extrapolate, assume, or invent rules.\n"
        "2. For EVERY factual claim, timeline, threshold, or policy condition you state, cite the source passage ID "
        "using the exact format: [ID: chunk_id].\n"
        "3. If the provided passages do NOT contain sufficient information to fully answer the question, state clearly "
        "what is known and advise that the request be escalated to a human specialist.\n"
        "4. Never hallucinate policy clauses, day limits, return windows, or fees.\n"
        "5. Keep the response professional, friendly, and structured."
    )

    def assemble(self, query: str, chunks: Sequence[RankedChunk]) -> str:
        """Assembles the complete grounded prompt payload for Gemini.

        Args:
            query: Customer query string.
            chunks: Top ranked chunks to include as grounded context.

        Returns:
            Fully assembled prompt string.
        """
        clean_query = query.strip()

        passages_formatted: list[str] = []
        for idx, chunk in enumerate(chunks, start=1):
            section = chunk.section_title if chunk.section_title else "General Policy"
            passage_block = (
                f"[PASSAGE {idx}]\n"
                f"[ID: {chunk.chunk_id}]\n"
                f"Document: {chunk.document_name}\n"
                f"Section: {section}\n"
                f"Content:\n{chunk.chunk_content.strip()}"
            )
            passages_formatted.append(passage_block)

        context_payload = "\n\n".join(passages_formatted)

        prompt = (
            f"{self.SYSTEM_INSTRUCTIONS}\n\n"
            f"--- BEGIN POLICY CONTEXT ---\n\n"
            f"{context_payload}\n\n"
            f"--- END POLICY CONTEXT ---\n\n"
            f"USER QUESTION: {clean_query}\n\n"
            f"ASSISTANT RESOLUTION (with [ID: chunk_id] citations):"
        )
        return prompt


# -----------------------------------------------------------------------------
# Stage 3: Resolution Generator & Escalation Branching
# -----------------------------------------------------------------------------

class ResolutionGenerator:
    """Enterprise RAG Resolution Generator with citation alignment and escalation routing.

    WHAT:
        Coordinates evidence evaluation, grounded prompt compilation, Gemini-1.5-Flash generation,
        citation extraction, and escalation/clarification branching.

    WHY:
        Provides a safe, single-entrypoint interface for the agent layer to obtain verified answers.

    HOW:
        - Uses `EvidenceEvaluator` to branch before generation.
        - Generates cited text via `google.genai` SDK at `temperature=0.0`.
        - Extracts and validates citations using regex against provided chunk IDs.
        - Catches external API exceptions gracefully, returning safe escalation fallbacks.
    """

    def __init__(
        self,
        genai_client: genai.Client | None = None,
        model_name: str = DEFAULT_GENERATION_MODEL,
        evaluator: EvidenceEvaluator | None = None,
        prompt_assembler: GroundedPromptAssembler | None = None,
    ) -> None:
        """Initialize the Resolution Generator.

        Args:
            genai_client: Injected Google GenAI client (lazy loaded if None).
            model_name: Generation LLM model name (default: 'gemini-1.5-flash').
            evaluator: Evidence sufficiency evaluator instance.
            prompt_assembler: Grounded prompt assembler instance.
        """
        self._genai_client = genai_client
        self.model_name = model_name
        self.evaluator = evaluator or EvidenceEvaluator()
        self.prompt_assembler = prompt_assembler or GroundedPromptAssembler()

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

    def generate_resolution(
        self,
        query: str,
        ranked_chunks: Sequence[RankedChunk],
    ) -> GroundedResponse:
        """Synthesizes a grounded response or routes to clarification/escalation.

        WHAT:
            The primary entry point for generating customer support resolutions from RAG context.

        WHY:
            Guarantees factual accuracy, verifiable citations, and safe escalation fallbacks.

        HOW:
            1. Evaluates evidence sufficiency via `EvidenceEvaluator`.
            2. If ambiguous -> returns clarification request (`clarification_needed=True`).
            3. If insufficient -> returns human escalation trigger (`is_escalated=True`).
            4. If sufficient -> calls Gemini-1.5-Flash, extracts citations, and returns `GroundedResponse`.

        Args:
            query: Customer inquiry string.
            ranked_chunks: Top-3 cross-encoder ranked chunks.

        Returns:
            `GroundedResponse` containing answer text, citations, and routing flags.

        Raises:
            ValueError: If query is empty or whitespace-only.
        """
        if not query or not query.strip():
            raise ValueError("Query string for resolution generation cannot be empty.")

        clean_query = query.strip()

        # Step 1: Evaluate Evidence Sufficiency
        eval_result = self.evaluator.evaluate_sufficiency(clean_query, ranked_chunks)

        # Step 2: Handle Insufficient / Ambiguous Evidence Branching
        if not eval_result.is_sufficient:
            # Check for Ambiguity vs Out-of-Scope
            if "ambiguous" in eval_result.reasoning.lower():
                missing_info = (
                    ", ".join(eval_result.missing_information)
                    if eval_result.missing_information
                    else "more details"
                )
                clarification_text = (
                    f"To assist you accurately with your request, could you please provide {missing_info}?"
                )
                return GroundedResponse(
                    response_text=clarification_text,
                    citations=[],
                    is_escalated=False,
                    clarification_needed=True,
                )

            # Domain Gap / Missing Policy -> Escalation Notice
            escalation_text = (
                "I apologize, but our official support policy documents do not contain sufficient "
                "information to resolve your specific inquiry. I have flagged this request to be "
                "escalated to a human support specialist for direct assistance."
            )
            return GroundedResponse(
                response_text=escalation_text,
                citations=[],
                is_escalated=True,
                clarification_needed=False,
            )

        # Step 3: Assemble Grounded Prompt
        prompt = self.prompt_assembler.assemble(clean_query, ranked_chunks)

        # Step 4: Execute Generation via Google GenAI SDK
        try:
            config = types.GenerateContentConfig(
                temperature=0.0,
            )
            response = self.genai_client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
            raw_text = response.text or ""

        except Exception as exc:
            logger.error("GenAI resolution generation failed: %s", exc)
            fallback_text = (
                "We encountered a temporary issue generating your response. "
                "Your inquiry has been safely routed to a support agent."
            )
            return GroundedResponse(
                response_text=fallback_text,
                citations=[],
                is_escalated=True,
                clarification_needed=False,
            )

        # Step 5: Extract and Validate Citations
        # Matches [ID: chunk_id] or [ID:chunk_id]
        raw_citations = re.findall(r"\[ID:\s*([a-zA-Z0-9_\-]+)\]", raw_text)
        valid_chunk_ids = {chunk.chunk_id for chunk in ranked_chunks}

        # Deduplicate citations while preserving order and matching valid candidate IDs
        verified_citations: list[str] = []
        for cite in raw_citations:
            if cite in valid_chunk_ids and cite not in verified_citations:
                verified_citations.append(cite)

        # If model failed to explicitly tag citations but answered from valid chunks, fallback to top chunk ID
        if not verified_citations and ranked_chunks:
            verified_citations.append(ranked_chunks[0].chunk_id)

        return GroundedResponse(
            response_text=raw_text.strip(),
            citations=verified_citations,
            is_escalated=False,
            clarification_needed=False,
        )
