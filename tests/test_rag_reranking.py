"""Unit and integration tests for ResolveX Reciprocal Rank Fusion & Cross-Encoder Re-Ranking (Step 5 — Phase 4).

Verifies:
1. RankedChunk domain model validation and constraints.
2. Reciprocal Rank Fusion (RRF) score calculations against exact mathematical values.
3. RRF deduplication when chunks appear in both Dense and Sparse retrieval streams.
4. RRF handling of disjoint lists (dense-only, sparse-only, empty streams).
5. RRF parameter validation (smoothing constant k, top_n truncation).
6. CrossEncoderReranker initialization and model loading.
7. FlashRank cross-attention scoring, score ordering, and top_k extraction.
8. Cross-Encoder handling of empty query, empty candidate pool, and candidate counts < top_k.
9. Cross-Encoder fallback when inference encounters errors.
10. Full Two-Stage pipeline integration test (Retrieval -> RRF -> Cross-Encoder).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.rag.reranking import (
    DEFAULT_FINAL_TOP_K,
    DEFAULT_RERANK_MODEL,
    DEFAULT_RRF_K,
    DEFAULT_RRF_TOP_N,
    CrossEncoderReranker,
    RankedChunk,
    reciprocal_rank_fusion,
)
from Backend.rag.retrieval import RetrievedChunk


# =============================================================================
# 1. Domain Model Tests
# =============================================================================

class TestRankedChunkModel:
    """Test suite for RankedChunk Pydantic model."""

    def test_valid_instantiation(self):
        chunk = RankedChunk(
            chunk_id="refund_policy_000",
            document_name="refund_policy.pdf",
            section_title="Refund Eligibility",
            chunk_content="7 days refund policy for damaged goods.",
            score=0.985,
            retrieval_type="hybrid",
            rrf_score=0.0325,
            rerank_score=0.985,
            final_rank=1,
        )
        assert chunk.chunk_id == "refund_policy_000"
        assert chunk.final_rank == 1
        assert chunk.score == 0.985
        assert chunk.rrf_score == 0.0325
        assert chunk.rerank_score == 0.985
        assert chunk.retrieval_type == "hybrid"

    def test_invalid_rank_raises_validation_error(self):
        with pytest.raises(Exception):
            RankedChunk(
                chunk_id="test_000",
                document_name="test.pdf",
                chunk_content="text",
                score=0.5,
                rrf_score=0.01,
                rerank_score=0.5,
                final_rank=0,  # invalid rank: must be ge=1
            )


# =============================================================================
# 2. Reciprocal Rank Fusion (RRF) Tests
# =============================================================================

class TestReciprocalRankFusion:
    """Test suite for Reciprocal Rank Fusion mathematical correctness and deduplication."""

    def test_rrf_mathematical_precision(self):
        """Verify exact manual RRF score calculation with k=60.
        
        Dense: [Chunk A (rank 1), Chunk B (rank 2)]
        Sparse: [Chunk B (rank 1), Chunk C (rank 2)]
        
        Score(Chunk B) = 1/(60+2) + 1/(60+1) = 1/62 + 1/61 = 0.01612903 + 0.01639344 = 0.032522
        Score(Chunk A) = 1/(60+1) = 1/61 = 0.016393
        Score(Chunk C) = 1/(60+2) = 1/62 = 0.016129
        """
        dense = [
            RetrievedChunk(
                chunk_id="chunk_a",
                document_name="doc_a.pdf",
                chunk_content="Content A",
                score=0.90,
                retrieval_type="dense",
            ),
            RetrievedChunk(
                chunk_id="chunk_b",
                document_name="doc_b.pdf",
                chunk_content="Content B",
                score=0.80,
                retrieval_type="dense",
            ),
        ]
        sparse = [
            RetrievedChunk(
                chunk_id="chunk_b",
                document_name="doc_b.pdf",
                chunk_content="Content B",
                score=0.50,
                retrieval_type="sparse",
            ),
            RetrievedChunk(
                chunk_id="chunk_c",
                document_name="doc_c.pdf",
                chunk_content="Content C",
                score=0.30,
                retrieval_type="sparse",
            ),
        ]

        fused = reciprocal_rank_fusion(dense, sparse, k=60, top_n=10)

        assert len(fused) == 3
        # Chunk B must be rank 1
        assert fused[0].chunk_id == "chunk_b"
        assert pytest.approx(fused[0].score, abs=1e-5) == 0.032522
        # Chunk A must be rank 2
        assert fused[1].chunk_id == "chunk_a"
        assert pytest.approx(fused[1].score, abs=1e-5) == 0.016393
        # Chunk C must be rank 3
        assert fused[2].chunk_id == "chunk_c"
        assert pytest.approx(fused[2].score, abs=1e-5) == 0.016129

    def test_rrf_deduplication_preserves_content_and_metadata(self):
        chunk1_dense = RetrievedChunk(
            chunk_id="refund_000",
            document_name="refund_policy.pdf",
            section_title="Eligibility",
            chunk_content="Full refund within 7 days",
            score=0.85,
            retrieval_type="dense",
        )
        chunk1_sparse = RetrievedChunk(
            chunk_id="refund_000",
            document_name="refund_policy.pdf",
            section_title="Eligibility",
            chunk_content="Full refund within 7 days",
            score=0.45,
            retrieval_type="sparse",
        )

        fused = reciprocal_rank_fusion([chunk1_dense], [chunk1_sparse], k=60)
        assert len(fused) == 1
        assert fused[0].chunk_id == "refund_000"
        assert fused[0].document_name == "refund_policy.pdf"
        assert fused[0].section_title == "Eligibility"
        assert fused[0].chunk_content == "Full refund within 7 days"

    def test_rrf_disjoint_lists(self):
        """Verify behavior when dense and sparse candidate sets share zero common chunks."""
        dense = [
            RetrievedChunk(
                chunk_id="dense_1",
                document_name="dense.pdf",
                chunk_content="Dense 1",
                score=0.9,
                retrieval_type="dense",
            )
        ]
        sparse = [
            RetrievedChunk(
                chunk_id="sparse_1",
                document_name="sparse.pdf",
                chunk_content="Sparse 1",
                score=0.8,
                retrieval_type="sparse",
            )
        ]

        fused = reciprocal_rank_fusion(dense, sparse, k=60)
        assert len(fused) == 2
        # Both share identical rank (rank 1 in their respective lists)
        assert fused[0].score == fused[1].score == round(1.0 / 61, 6)

    def test_rrf_empty_inputs(self):
        assert reciprocal_rank_fusion([], []) == []

        dense = [
            RetrievedChunk(
                chunk_id="dense_1",
                document_name="dense.pdf",
                chunk_content="Dense 1",
                score=0.9,
                retrieval_type="dense",
            )
        ]
        assert len(reciprocal_rank_fusion(dense, [])) == 1
        assert len(reciprocal_rank_fusion([], dense)) == 1

    def test_rrf_top_n_truncation(self):
        chunks = [
            RetrievedChunk(
                chunk_id=f"chunk_{i}",
                document_name="doc.pdf",
                chunk_content=f"Content {i}",
                score=1.0 / (i + 1),
                retrieval_type="dense",
            )
            for i in range(10)
        ]
        fused = reciprocal_rank_fusion(chunks, [], top_n=3)
        assert len(fused) == 3

    def test_rrf_invalid_k_raises_error(self):
        with pytest.raises(ValueError, match="must be non-negative"):
            reciprocal_rank_fusion([], [], k=-1)


# =============================================================================
# 3. Cross-Encoder Re-Ranker Tests (FlashRank)
# =============================================================================

class TestCrossEncoderReranker:
    """Test suite for FlashRank Cross-Encoder scoring and ranking."""

    def test_initialization_defaults(self):
        reranker = CrossEncoderReranker()
        assert reranker.model_name == DEFAULT_RERANK_MODEL
        assert reranker.max_length == 512
        assert reranker.cache_dir is None

    def test_rerank_empty_candidates_returns_empty_list(self):
        reranker = CrossEncoderReranker()
        assert reranker.rerank("any query", []) == []

    def test_rerank_empty_query_raises_value_error(self):
        reranker = CrossEncoderReranker()
        candidates = [
            RetrievedChunk(
                chunk_id="c1",
                document_name="d.pdf",
                chunk_content="content",
                score=0.5,
                retrieval_type="dense",
            )
        ]
        with pytest.raises(ValueError, match="cannot be empty"):
            reranker.rerank("", candidates)
        with pytest.raises(ValueError, match="cannot be empty"):
            reranker.rerank("   ", candidates)

    def test_rerank_real_flashrank_inference_accuracy(self):
        """Live inference test on CPU using FlashRank ms-marco-TinyBERT-L-2-v2."""
        reranker = CrossEncoderReranker()

        # Create 4 test candidates: 1 highly relevant, 1 moderately relevant, 2 irrelevant
        candidates = [
            RetrievedChunk(
                chunk_id="account_000",
                document_name="account_policy.pdf",
                section_title="Account Password",
                chunk_content="To reset your password, visit the security settings page and click reset.",
                score=0.016,
                retrieval_type="dense",
            ),
            RetrievedChunk(
                chunk_id="refund_000",
                document_name="refund_policy.pdf",
                section_title="Refund Policy",
                chunk_content="Customers can request a full refund within 7 days of package delivery for defective items.",
                score=0.032,
                retrieval_type="dense",
            ),
            RetrievedChunk(
                chunk_id="shipping_000",
                document_name="shipping_policy.pdf",
                section_title="Shipping Options",
                chunk_content="Standard courier shipping takes 3 to 5 business days across domestic zones.",
                score=0.015,
                retrieval_type="sparse",
            ),
        ]

        query = "What is the refund policy window for returning defective items?"
        ranked = reranker.rerank(query=query, candidates=candidates, top_k=2)

        assert len(ranked) == 2
        # Most relevant chunk must be refund_000
        assert ranked[0].chunk_id == "refund_000"
        assert ranked[0].final_rank == 1
        assert ranked[0].rerank_score > ranked[1].rerank_score
        assert ranked[1].final_rank == 2

    def test_rerank_fewer_candidates_than_top_k(self):
        reranker = CrossEncoderReranker()
        candidates = [
            RetrievedChunk(
                chunk_id="c1",
                document_name="doc.pdf",
                chunk_content="Policy content 1",
                score=0.5,
                retrieval_type="dense",
            )
        ]
        ranked = reranker.rerank("test query", candidates, top_k=5)
        assert len(ranked) == 1
        assert ranked[0].final_rank == 1

    def test_rerank_fallback_on_inference_error(self):
        """When FlashRank encounters an unexpected error, gracefully falls back to candidate RRF order."""
        reranker = CrossEncoderReranker()
        mock_ranker = MagicMock()
        mock_ranker.rerank.side_effect = RuntimeError("ONNX Runtime Exception")

        with patch.object(reranker, "_ranker", mock_ranker):
            candidates = [
                RetrievedChunk(
                    chunk_id="c1",
                    document_name="doc1.pdf",
                    chunk_content="Content 1",
                    score=0.032,
                    retrieval_type="dense",
                ),
                RetrievedChunk(
                    chunk_id="c2",
                    document_name="doc2.pdf",
                    chunk_content="Content 2",
                    score=0.016,
                    retrieval_type="sparse",
                ),
            ]
            ranked = reranker.rerank("query", candidates, top_k=2)

            assert len(ranked) == 2
            assert ranked[0].chunk_id == "c1"
            assert ranked[0].final_rank == 1
            assert ranked[1].chunk_id == "c2"
            assert ranked[1].final_rank == 2


# =============================================================================
# 4. End-to-End Two-Stage Pipeline Integration Test
# =============================================================================

class TestTwoStageRerankingIntegration:
    """Integration test simulating retrieval outputs passed through RRF and Cross-Encoder."""

    def test_full_two_stage_pipeline_flow(self):
        # 1. Simulated Dense stream
        dense_results = [
            RetrievedChunk(
                chunk_id="refund_000",
                document_name="refund_policy.pdf",
                section_title="Refunds",
                chunk_content="Returns accepted within 7 calendar days of receipt.",
                score=0.88,
                retrieval_type="dense",
            ),
            RetrievedChunk(
                chunk_id="cancellation_000",
                document_name="cancellation_policy.pdf",
                section_title="Cancellations",
                chunk_content="Orders can be cancelled prior to dispatch shipment.",
                score=0.75,
                retrieval_type="dense",
            ),
        ]

        # 2. Simulated Sparse stream
        sparse_results = [
            RetrievedChunk(
                chunk_id="refund_000",
                document_name="refund_policy.pdf",
                section_title="Refunds",
                chunk_content="Returns accepted within 7 calendar days of receipt.",
                score=0.42,
                retrieval_type="sparse",
            ),
            RetrievedChunk(
                chunk_id="shipping_000",
                document_name="shipping_policy.pdf",
                section_title="Shipping",
                chunk_content="Tracking ID will be emailed once dispatched.",
                score=0.35,
                retrieval_type="sparse",
            ),
        ]

        # Stage 1: Reciprocal Rank Fusion
        fused_pool = reciprocal_rank_fusion(dense_results, sparse_results, k=60, top_n=20)
        assert len(fused_pool) == 3
        assert fused_pool[0].chunk_id == "refund_000"

        # Stage 2: Cross-Encoder Re-Ranking
        reranker = CrossEncoderReranker()
        final_top3 = reranker.rerank(
            query="Can I return an item after receiving it?",
            candidates=fused_pool,
            top_k=3,
        )

        assert len(final_top3) == 3
        assert final_top3[0].chunk_id == "refund_000"
        assert final_top3[0].final_rank == 1
        assert "7 calendar days" in final_top3[0].chunk_content
        assert final_top3[0].score > 0
