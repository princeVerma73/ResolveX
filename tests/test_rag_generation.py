"""Unit and integration tests for ResolveX Evidence Evaluation & Grounded Generation (Step 5 — Phase 5).

Verifies:
1. EvaluationResult and GroundedResponse domain models validation.
2. EvidenceEvaluator sufficiency logic (empty chunks, ambiguous queries, low confidence, sufficient context).
3. GroundedPromptAssembler formatting, delimiter encapsulation, and citation tagging.
4. ResolutionGenerator with mocked Gemini API (sufficient evidence with verified citations).
5. ResolutionGenerator escalation routing (insufficient evidence / out-of-scope queries).
6. ResolutionGenerator clarification routing (underspecified / ambiguous queries).
7. Resilience & fallback handling on GenAI API errors.
8. End-to-end full pipeline verification (Retrieval -> RRF -> Cross-Encoder -> Grounded Generation).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.rag.generation import (
    DEFAULT_GENERATION_MODEL,
    MIN_CONFIDENCE_THRESHOLD,
    EvaluationResult,
    EvidenceEvaluator,
    GroundedPromptAssembler,
    GroundedResponse,
    ResolutionGenerator,
)
from Backend.rag.reranking import CrossEncoderReranker, RankedChunk, reciprocal_rank_fusion
from Backend.rag.retrieval import RetrievedChunk


# =============================================================================
# 1. Domain Model Tests
# =============================================================================

class TestGenerationModels:
    """Test suite for Phase 5 Pydantic domain models."""

    def test_evaluation_result_instantiation(self):
        res = EvaluationResult(
            is_sufficient=True,
            confidence_score=0.95,
            reasoning="Sufficient evidence present",
            missing_information=[],
        )
        assert res.is_sufficient is True
        assert res.confidence_score == 0.95
        assert res.missing_information == []

    def test_grounded_response_instantiation(self):
        resp = GroundedResponse(
            response_text="Refunds are available within 7 days [ID: refund_policy_000].",
            citations=["refund_policy_000"],
            is_escalated=False,
            clarification_needed=False,
        )
        assert resp.response_text.startswith("Refunds")
        assert resp.citations == ["refund_policy_000"]
        assert resp.is_escalated is False
        assert resp.clarification_needed is False


# =============================================================================
# 2. Evidence Evaluator Tests
# =============================================================================

class TestEvidenceEvaluator:
    """Test suite for EvidenceEvaluator completeness checks and thresholding."""

    def test_empty_chunks_returns_insufficient(self):
        evaluator = EvidenceEvaluator()
        result = evaluator.evaluate_sufficiency("How to return an item?", [])
        assert result.is_sufficient is False
        assert result.confidence_score == 0.0
        assert "No relevant policy chunks" in result.reasoning
        assert "Relevant policy documentation" in result.missing_information

    def test_ambiguous_short_query_returns_insufficient(self):
        evaluator = EvidenceEvaluator()
        chunks = [
            RankedChunk(
                chunk_id="refund_000",
                document_name="refund_policy.pdf",
                chunk_content="Refund policy content",
                score=0.8,
                retrieval_type="hybrid",
                rrf_score=0.03,
                rerank_score=0.8,
                final_rank=1,
            )
        ]
        result = evaluator.evaluate_sufficiency("refund", chunks)
        assert result.is_sufficient is False
        assert "ambiguous" in result.reasoning.lower()
        assert len(result.missing_information) > 0

    def test_low_confidence_score_below_threshold_returns_insufficient(self):
        evaluator = EvidenceEvaluator(confidence_threshold=0.01)
        chunks = [
            RankedChunk(
                chunk_id="faq_000",
                document_name="faq.pdf",
                chunk_content="Generic FAQ info",
                score=0.00005,
                retrieval_type="hybrid",
                rrf_score=0.001,
                rerank_score=0.00005,
                final_rank=1,
            )
        ]
        result = evaluator.evaluate_sufficiency("Custom corporate SLA guarantees?", chunks)
        assert result.is_sufficient is False
        assert "below the confidence floor" in result.reasoning

    def test_high_confidence_returns_sufficient(self):
        evaluator = EvidenceEvaluator()
        chunks = [
            RankedChunk(
                chunk_id="refund_policy_000",
                document_name="refund_policy.pdf",
                section_title="Eligibility",
                chunk_content="Customers can request a refund within 7 days.",
                score=0.92,
                retrieval_type="hybrid",
                rrf_score=0.032,
                rerank_score=0.92,
                final_rank=1,
            )
        ]
        result = evaluator.evaluate_sufficiency("What is the return window for items?", chunks)
        assert result.is_sufficient is True
        assert result.confidence_score == 0.92
        assert len(result.missing_information) == 0


# =============================================================================
# 3. Grounded Prompt Assembler Tests
# =============================================================================

class TestGroundedPromptAssembler:
    """Test suite for prompt serialization and delimiter encapsulation."""

    def test_assemble_contains_required_sections_and_tags(self):
        assembler = GroundedPromptAssembler()
        chunks = [
            RankedChunk(
                chunk_id="shipping_policy_000",
                document_name="shipping_policy.pdf",
                section_title="Delivery Times",
                chunk_content="Standard shipping takes 3-5 business days.",
                score=0.95,
                retrieval_type="hybrid",
                rrf_score=0.032,
                rerank_score=0.95,
                final_rank=1,
            ),
            RankedChunk(
                chunk_id="shipping_policy_001",
                document_name="shipping_policy.pdf",
                section_title=None,
                chunk_content="Express shipping takes 1-2 business days.",
                score=0.85,
                retrieval_type="hybrid",
                rrf_score=0.016,
                rerank_score=0.85,
                final_rank=2,
            ),
        ]
        query = "How long does standard shipping take?"
        prompt = assembler.assemble(query, chunks)

        assert "--- BEGIN POLICY CONTEXT ---" in prompt
        assert "--- END POLICY CONTEXT ---" in prompt
        assert "[ID: shipping_policy_000]" in prompt
        assert "Document: shipping_policy.pdf" in prompt
        assert "Section: Delivery Times" in prompt
        assert "[ID: shipping_policy_001]" in prompt
        assert "Section: General Policy" in prompt
        assert "USER QUESTION: How long does standard shipping take?" in prompt
        assert "[ID: chunk_id] citations" in prompt


# =============================================================================
# 4. Resolution Generator & Routing Tests
# =============================================================================

class TestResolutionGenerator:
    """Test suite for ResolutionGenerator execution, citation extraction, and routing."""

    def test_empty_query_raises_value_error(self):
        generator = ResolutionGenerator()
        with pytest.raises(ValueError, match="cannot be empty"):
            generator.generate_resolution("", [])

    def test_sufficient_evidence_generates_cited_response(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "You are eligible for a full refund within 7 days of package delivery [ID: refund_policy_000]."
        )
        mock_genai.models.generate_content.return_value = mock_response

        generator = ResolutionGenerator(genai_client=mock_genai)
        chunks = [
            RankedChunk(
                chunk_id="refund_policy_000",
                document_name="refund_policy.pdf",
                section_title="Eligibility",
                chunk_content="Full refund within 7 days of delivery.",
                score=0.95,
                retrieval_type="hybrid",
                rrf_score=0.032,
                rerank_score=0.95,
                final_rank=1,
            )
        ]

        response = generator.generate_resolution(
            query="What is the refund deadline for items?",
            ranked_chunks=chunks,
        )

        assert response.is_escalated is False
        assert response.clarification_needed is False
        assert response.citations == ["refund_policy_000"]
        assert "7 days" in response.response_text
        mock_genai.models.generate_content.assert_called_once()
        _, kwargs = mock_genai.models.generate_content.call_args
        assert kwargs["config"].temperature == 0.0

    def test_insufficient_evidence_escalates_gracefully(self):
        mock_genai = MagicMock()
        generator = ResolutionGenerator(genai_client=mock_genai)

        # Empty chunks simulate out-of-scope retrieval
        response = generator.generate_resolution(
            query="Can I speak with the CEO directly?",
            ranked_chunks=[],
        )

        assert response.is_escalated is True
        assert response.clarification_needed is False
        assert response.citations == []
        assert "escalated to a human support specialist" in response.response_text
        # GenAI API must NOT be called when evidence is insufficient
        mock_genai.models.generate_content.assert_not_called()

    def test_ambiguous_query_requests_clarification(self):
        mock_genai = MagicMock()
        generator = ResolutionGenerator(genai_client=mock_genai)

        chunks = [
            RankedChunk(
                chunk_id="refund_000",
                document_name="refund_policy.pdf",
                chunk_content="Refund policy content",
                score=0.8,
                retrieval_type="hybrid",
                rrf_score=0.03,
                rerank_score=0.8,
                final_rank=1,
            )
        ]

        response = generator.generate_resolution(
            query="cancel",
            ranked_chunks=chunks,
        )

        assert response.clarification_needed is True
        assert response.is_escalated is False
        assert "could you please provide" in response.response_text
        mock_genai.models.generate_content.assert_not_called()

    def test_genai_api_error_falls_back_to_safe_escalation(self):
        mock_genai = MagicMock()
        mock_genai.models.generate_content.side_effect = RuntimeError("API Quota Exceeded 429")

        generator = ResolutionGenerator(genai_client=mock_genai)
        chunks = [
            RankedChunk(
                chunk_id="payment_000",
                document_name="payment_policy.pdf",
                chunk_content="UPI payment verification takes 24 hours.",
                score=0.90,
                retrieval_type="hybrid",
                rrf_score=0.032,
                rerank_score=0.90,
                final_rank=1,
            )
        ]

        response = generator.generate_resolution(
            query="How long for UPI verification?",
            ranked_chunks=chunks,
        )

        assert response.is_escalated is True
        assert "safely routed to a support agent" in response.response_text


# =============================================================================
# 5. Full End-to-End RAG Pipeline Test
# =============================================================================

class TestFullRAGPipelineIntegration:
    """End-to-End test executing all 5 phases of the ResolveX RAG Pipeline."""

    def test_complete_rag_query_to_grounded_response_lifecycle(self):
        # 1. Retrieval Phase output
        dense_results = [
            RetrievedChunk(
                chunk_id="refund_policy_000",
                document_name="refund_policy.pdf",
                section_title="Eligibility",
                chunk_content="Customers can request a refund within 7 calendar days of receipt.",
                score=0.89,
                retrieval_type="dense",
            )
        ]
        sparse_results = [
            RetrievedChunk(
                chunk_id="refund_policy_000",
                document_name="refund_policy.pdf",
                section_title="Eligibility",
                chunk_content="Customers can request a refund within 7 calendar days of receipt.",
                score=0.45,
                retrieval_type="sparse",
            )
        ]

        # 2. Stage 1: RRF Fusion
        fused_candidates = reciprocal_rank_fusion(dense_results, sparse_results, k=60, top_n=10)
        assert len(fused_candidates) == 1
        assert fused_candidates[0].chunk_id == "refund_policy_000"

        # 3. Stage 2: Cross-Encoder Reranking
        reranker = CrossEncoderReranker()
        top_chunks = reranker.rerank(
            query="How many days do I have to return an order?",
            candidates=fused_candidates,
            top_k=3,
        )
        assert len(top_chunks) == 1
        assert top_chunks[0].chunk_id == "refund_policy_000"
        assert top_chunks[0].final_rank == 1

        # 4. Stage 3: Grounded Generation with Mocked LLM
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "You have 7 calendar days from receipt to request a refund [ID: refund_policy_000]."
        mock_genai.models.generate_content.return_value = mock_response

        generator = ResolutionGenerator(genai_client=mock_genai)
        final_resolution = generator.generate_resolution(
            query="How many days do I have to return an order?",
            ranked_chunks=top_chunks,
        )

        assert final_resolution.is_escalated is False
        assert final_resolution.clarification_needed is False
        assert "7 calendar days" in final_resolution.response_text
        assert final_resolution.citations == ["refund_policy_000"]
