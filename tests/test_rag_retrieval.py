"""Unit and integration tests for ResolveX Hybrid Retrieval Engine (Step 5 — Phase 3).

Verifies:
1. RetrievedChunk domain model validation and attributes.
2. HybridRetriever initialization, configuration defaults, and client properties.
3. Custom exceptions (RetrievalError) formatting and details.
4. embed_query generation with task_type="RETRIEVAL_QUERY" and dimensional invariant.
5. Dense search using Supabase RPC and cosine distance ranking.
6. Sparse search using Supabase RPC / PostgREST fallback and cover density ranking.
7. Parallel retrieval concurrency and fault isolation (one stream fails, other succeeds).
8. Total retrieval failure handling when both branches fail.
9. Edge cases: punctuation-heavy queries, non-existent terms, numeric codes, and empty queries.
10. Async parallel retrieval coroutine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.core.exceptions import DatabaseOperationError
from Backend.rag.ingestion import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingGenerationError,
)
from Backend.rag.retrieval import (
    HybridRetriever,
    RetrievalError,
    RetrievedChunk,
)


# =============================================================================
# 1. RetrievedChunk Model & Exception Tests
# =============================================================================

class TestRetrievedChunkModel:
    """Test suite for RetrievedChunk Pydantic domain model."""

    def test_valid_instantiation_dense(self):
        chunk = RetrievedChunk(
            chunk_id="refund_policy_000",
            document_name="refund_policy.pdf",
            section_title="Refund Eligibility",
            chunk_content="Full refund within 7 days of delivery.",
            score=0.92,
            retrieval_type="dense",
        )
        assert chunk.chunk_id == "refund_policy_000"
        assert chunk.document_name == "refund_policy.pdf"
        assert chunk.section_title == "Refund Eligibility"
        assert chunk.score == 0.92
        assert chunk.retrieval_type == "dense"

    def test_valid_instantiation_sparse(self):
        chunk = RetrievedChunk(
            chunk_id="shipping_policy_001",
            document_name="shipping_policy.pdf",
            section_title=None,
            chunk_content="Tracking details will be emailed within 24 hours.",
            score=0.45,
            retrieval_type="sparse",
        )
        assert chunk.chunk_id == "shipping_policy_001"
        assert chunk.section_title is None
        assert chunk.score == 0.45
        assert chunk.retrieval_type == "sparse"

    def test_invalid_retrieval_type_raises_validation_error(self):
        with pytest.raises(Exception):
            RetrievedChunk(
                chunk_id="test_000",
                document_name="test.pdf",
                chunk_content="content",
                score=1.0,
                retrieval_type="keyword",  # invalid literal
            )

    def test_custom_exception_formatting(self):
        err = RetrievalError(
            message="Both branches failed",
            query="return item",
            details={"error_code": 500},
        )
        assert err.query == "return item"
        assert err.details["error_code"] == 500
        assert "Both branches failed" in str(err)


# =============================================================================
# 2. Retriever Config & embed_query Tests
# =============================================================================

class TestHybridRetrieverConfigAndEmbed:
    """Test suite for HybridRetriever initialization and query embedding."""

    def test_default_initialization(self):
        retriever = HybridRetriever()
        assert retriever.dimension == 768
        assert retriever.model_name == DEFAULT_EMBEDDING_MODEL
        assert retriever.max_retries == 4
        assert retriever.base_delay_seconds == 1.0

    def test_custom_initialization(self):
        mock_db = MagicMock()
        mock_genai = MagicMock()
        retriever = HybridRetriever(
            supabase_client=mock_db,
            genai_client=mock_genai,
            model_name="models/custom-embed",
            dimension=768,
            max_retries=2,
            base_delay_seconds=0.01,
        )
        assert retriever.supabase_client is mock_db
        assert retriever.genai_client is mock_genai
        assert retriever.model_name == "models/custom-embed"

    def test_embed_query_empty_raises_value_error(self):
        retriever = HybridRetriever(genai_client=MagicMock())
        with pytest.raises(ValueError, match="cannot be empty"):
            retriever.embed_query("")
        with pytest.raises(ValueError, match="cannot be empty"):
            retriever.embed_query("   ")

    def test_embed_query_success(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.05] * 768
        mock_response.embeddings = [mock_embedding]
        mock_genai.models.embed_content.return_value = mock_response

        retriever = HybridRetriever(genai_client=mock_genai)
        vector = retriever.embed_query("How do I return my order?")

        assert len(vector) == 768
        assert vector[0] == 0.05
        mock_genai.models.embed_content.assert_called_once()
        _, kwargs = mock_genai.models.embed_content.call_args
        assert kwargs["config"].task_type == "RETRIEVAL_QUERY"
        assert kwargs["config"].output_dimensionality == 768

    def test_embed_query_dimension_mismatch_raises_error(self):
        mock_genai = MagicMock()
        mock_response = MagicMock()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1] * 512  # Incorrect dimension
        mock_response.embeddings = [mock_embedding]
        mock_genai.models.embed_content.return_value = mock_response

        retriever = HybridRetriever(genai_client=mock_genai, max_retries=2, base_delay_seconds=0.01)
        with pytest.raises(EmbeddingGenerationError, match="Failed to generate query embedding"):
            retriever.embed_query("Valid query")


# =============================================================================
# 3. Dense Search Unit Tests
# =============================================================================

class TestDenseSearch:
    """Test suite for dense vector similarity search."""

    def test_dense_search_invalid_dimension(self):
        retriever = HybridRetriever(supabase_client=MagicMock())
        with pytest.raises(ValueError, match="dimension mismatch"):
            retriever.dense_search([0.1] * 100)

    def test_dense_search_rpc_success(self):
        mock_db = MagicMock()
        mock_rpc = MagicMock()
        mock_db.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value.data = [
            {
                "chunk_id": "refund_policy_000",
                "document_name": "refund_policy.pdf",
                "section_title": "Eligibility",
                "chunk_content": "7-day return window",
                "similarity": 0.88,
            },
            {
                "chunk_id": "refund_policy_001",
                "document_name": "refund_policy.pdf",
                "section_title": "Processing",
                "chunk_content": "5-7 business days",
                "similarity": 0.76,
            },
        ]

        retriever = HybridRetriever(supabase_client=mock_db)
        results = retriever.dense_search([0.01] * 768, limit=10)

        assert len(results) == 2
        assert results[0].chunk_id == "refund_policy_000"
        assert results[0].score == 0.88
        assert results[0].retrieval_type == "dense"
        assert results[1].score == 0.76
        mock_db.rpc.assert_called_once_with(
            "match_knowledge_dense",
            {"query_embedding": [0.01] * 768, "match_count": 10},
        )

    def test_dense_search_database_error_wrapping(self):
        mock_db = MagicMock()
        mock_db.rpc.side_effect = RuntimeError("PostgREST connection timeout")

        retriever = HybridRetriever(supabase_client=mock_db)
        with pytest.raises(DatabaseOperationError) as exc_info:
            retriever.dense_search([0.01] * 768)

        assert exc_info.value.operation == "dense_search"
        assert "dense_search" in exc_info.value.message or "Dense vector" in exc_info.value.message


# =============================================================================
# 4. Sparse Search Unit Tests
# =============================================================================

class TestSparseSearch:
    """Test suite for sparse lexical search and fallback mechanisms."""

    def test_sparse_search_empty_query_returns_empty_list(self):
        retriever = HybridRetriever(supabase_client=MagicMock())
        assert retriever.sparse_search("") == []
        assert retriever.sparse_search("   ") == []

    def test_sparse_search_rpc_success(self):
        mock_db = MagicMock()
        mock_rpc = MagicMock()
        mock_db.rpc.return_value = mock_rpc
        mock_rpc.execute.return_value.data = [
            {
                "chunk_id": "payment_policy_000",
                "document_name": "payment_policy.pdf",
                "section_title": "Payment Verification",
                "chunk_content": "UPI and Credit Card verification",
                "score": 0.52,
            }
        ]

        retriever = HybridRetriever(supabase_client=mock_db)
        results = retriever.sparse_search("UPI verification", limit=5)

        assert len(results) == 1
        assert results[0].chunk_id == "payment_policy_000"
        assert results[0].score == 0.52
        assert results[0].retrieval_type == "sparse"
        mock_db.rpc.assert_called_once_with(
            "match_knowledge_sparse",
            {"query_text": "UPI verification", "match_count": 5},
        )

    def test_sparse_search_rpc_failure_falls_back_to_postgrest(self):
        mock_db = MagicMock()
        # RPC fails
        mock_db.rpc.side_effect = RuntimeError("RPC match_knowledge_sparse not found")
        # PostgREST table fallback succeeds
        mock_table = MagicMock()
        mock_db.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_text_search = MagicMock()
        mock_select.text_search.return_value = mock_text_search
        mock_limit = MagicMock()
        mock_text_search.limit.return_value = mock_limit
        mock_limit.execute.return_value.data = [
            {
                "chunk_id": "shipping_policy_000",
                "document_name": "shipping_policy.pdf",
                "section_title": "Standard Shipping",
                "chunk_content": "Standard shipping takes 3-5 business days.",
            }
        ]

        retriever = HybridRetriever(supabase_client=mock_db)
        results = retriever.sparse_search("shipping days")

        assert len(results) == 1
        assert results[0].chunk_id == "shipping_policy_000"
        assert results[0].retrieval_type == "sparse"
        assert results[0].score == 1.0


# =============================================================================
# 5. Parallel Dispatch & Fault Isolation Tests
# =============================================================================

class TestParallelRetrievalAndFaultTolerance:
    """Test suite for concurrent execution, branch isolation, and error tolerance."""

    def test_retrieve_parallel_empty_query_raises_value_error(self):
        retriever = HybridRetriever()
        with pytest.raises(ValueError, match="cannot be empty"):
            retriever.retrieve_parallel("")

    def test_retrieve_parallel_both_succeed(self):
        mock_retriever = HybridRetriever()
        dense_chunk = RetrievedChunk(
            chunk_id="faq_000",
            document_name="faq.pdf",
            chunk_content="FAQ content",
            score=0.95,
            retrieval_type="dense",
        )
        sparse_chunk = RetrievedChunk(
            chunk_id="faq_001",
            document_name="faq.pdf",
            chunk_content="FAQ details",
            score=0.40,
            retrieval_type="sparse",
        )

        with patch.object(mock_retriever, "embed_query", return_value=[0.1] * 768), \
             patch.object(mock_retriever, "dense_search", return_value=[dense_chunk]), \
             patch.object(mock_retriever, "sparse_search", return_value=[sparse_chunk]):
            
            dense_res, sparse_res = mock_retriever.retrieve_parallel("How to track?", limit=10)

            assert len(dense_res) == 1
            assert dense_res[0].chunk_id == "faq_000"
            assert len(sparse_res) == 1
            assert sparse_res[0].chunk_id == "faq_001"

    def test_retrieve_parallel_dense_fails_sparse_succeeds(self):
        """Fault isolation: Dense branch fails (API error), Sparse branch gracefully carries the search."""
        mock_retriever = HybridRetriever()
        sparse_chunk = RetrievedChunk(
            chunk_id="cancellation_policy_000",
            document_name="cancellation_policy.pdf",
            chunk_content="Cancel before shipment",
            score=0.65,
            retrieval_type="sparse",
        )

        with patch.object(mock_retriever, "embed_query", side_effect=RuntimeError("Google API 503 Outage")), \
             patch.object(mock_retriever, "sparse_search", return_value=[sparse_chunk]):
            
            dense_res, sparse_res = mock_retriever.retrieve_parallel("cancel order")

            assert dense_res == []
            assert len(sparse_res) == 1
            assert sparse_res[0].chunk_id == "cancellation_policy_000"

    def test_retrieve_parallel_sparse_fails_dense_succeeds(self):
        """Fault isolation: Sparse branch fails (SQL error), Dense branch gracefully carries the search."""
        mock_retriever = HybridRetriever()
        dense_chunk = RetrievedChunk(
            chunk_id="account_policy_000",
            document_name="account_policy.pdf",
            chunk_content="Password reset steps",
            score=0.81,
            retrieval_type="dense",
        )

        with patch.object(mock_retriever, "embed_query", return_value=[0.1] * 768), \
             patch.object(mock_retriever, "dense_search", return_value=[dense_chunk]), \
             patch.object(mock_retriever, "sparse_search", side_effect=DatabaseOperationError(message="DB timeout", operation="sparse_search")):
            
            dense_res, sparse_res = mock_retriever.retrieve_parallel("reset password")

            assert len(dense_res) == 1
            assert dense_res[0].chunk_id == "account_policy_000"
            assert sparse_res == []

    def test_retrieve_parallel_both_fail_raises_retrieval_error(self):
        """When both streams encounter fatal errors, raise typed RetrievalError."""
        mock_retriever = HybridRetriever()

        with patch.object(mock_retriever, "embed_query", side_effect=RuntimeError("API down")), \
             patch.object(mock_retriever, "sparse_search", side_effect=RuntimeError("DB down")):
            
            with pytest.raises(RetrievalError) as exc_info:
                mock_retriever.retrieve_parallel("query with dual failure")
            
            assert "Both dense and sparse retrieval branches failed" in str(exc_info.value)
            assert exc_info.value.query == "query with dual failure"

    @pytest.mark.asyncio
    async def test_async_retrieve_parallel(self):
        mock_retriever = HybridRetriever()
        dense_chunk = RetrievedChunk(
            chunk_id="faq_000",
            document_name="faq.pdf",
            chunk_content="FAQ content",
            score=0.91,
            retrieval_type="dense",
        )

        with patch.object(mock_retriever, "retrieve_parallel", return_value=([dense_chunk], [])):
            dense_res, sparse_res = await mock_retriever.async_retrieve_parallel("async query", limit=5)
            assert len(dense_res) == 1
            assert sparse_res == []


# =============================================================================
# 6. Edge Cases & Query Syntax Tests
# =============================================================================

class TestQueryEdgeCases:
    """Test suite for edge case queries (punctuation, alphanumeric codes, syntax)."""

    def test_punctuation_heavy_query(self):
        mock_retriever = HybridRetriever()
        with patch.object(mock_retriever, "embed_query", return_value=[0.02] * 768), \
             patch.object(mock_retriever, "dense_search", return_value=[]), \
             patch.object(mock_retriever, "sparse_search", return_value=[]):
            
            dense, sparse = mock_retriever.retrieve_parallel("??? $#@! refund %&* ???")
            assert dense == []
            assert sparse == []

    def test_alphanumeric_policy_code_query(self):
        mock_retriever = HybridRetriever()
        chunk = RetrievedChunk(
            chunk_id="cancellation_policy_000",
            document_name="cancellation_policy.pdf",
            chunk_content="Clause POL-001 stipulates cancellation rules.",
            score=0.98,
            retrieval_type="sparse",
        )
        with patch.object(mock_retriever, "embed_query", return_value=[0.03] * 768), \
             patch.object(mock_retriever, "dense_search", return_value=[]), \
             patch.object(mock_retriever, "sparse_search", return_value=[chunk]):
            
            dense, sparse = mock_retriever.retrieve_parallel("POL-001 clause", limit=5)
            assert len(sparse) == 1
            assert "POL-001" in sparse[0].chunk_content

    def test_numeric_threshold_query(self):
        mock_retriever = HybridRetriever()
        chunk = RetrievedChunk(
            chunk_id="refund_policy_000",
            document_name="refund_policy.pdf",
            chunk_content="7 days return window for eligible items",
            score=0.87,
            retrieval_type="dense",
        )
        with patch.object(mock_retriever, "embed_query", return_value=[0.04] * 768), \
             patch.object(mock_retriever, "dense_search", return_value=[chunk]), \
             patch.object(mock_retriever, "sparse_search", return_value=[]):
            
            dense, sparse = mock_retriever.retrieve_parallel("7 days refund limit", limit=5)
            assert len(dense) == 1
            assert "7 days" in dense[0].chunk_content
