"""Unit and integration tests for ResolveX RAG Ingestion Pipeline (Step 5 — Phase 2).

Verifies:
1. PolicyIngestionEngine initialization, configuration defaults, and client properties.
2. Custom exceptions (EmbeddingGenerationError, IngestionPipelineError) formatting and details.
3. Single and batch embedding generation with Google GenAI SDK.
4. Dimensionality validation (enforcing exact 768-dim vectors).
5. Input guards (rejecting empty or whitespace strings).
6. Transient failure retry and backoff mechanics.
7. embed_chunks payload assembly and provenance metadata binding.
8. Idempotent batch upserting into Supabase knowledge_embeddings.
9. Database error handling and exception chaining.
10. Post-ingestion verification and dimensional audit.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Backend.core.exceptions import DatabaseOperationError
from Backend.rag.chunking import DocumentChunk
from Backend.rag.ingestion import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    KNOWLEDGE_TABLE_NAME,
    EmbeddingGenerationError,
    IngestionPipelineError,
    PolicyIngestionEngine,
)


# =============================================================================
# 1. Engine Initialization & Configuration Tests
# =============================================================================

class TestPolicyIngestionEngineConfig:
    """Test suite for PolicyIngestionEngine initialization and default settings."""

    def test_default_initialization(self):
        engine = PolicyIngestionEngine()
        assert engine.dimension == 768
        assert engine.batch_size == 32
        assert engine.table_name == "knowledge_embeddings"
        assert engine.max_retries == 4
        assert engine.base_delay_seconds == 1.0

    def test_custom_parameters(self):
        mock_db = MagicMock()
        mock_genai = MagicMock()
        engine = PolicyIngestionEngine(
            supabase_client=mock_db,
            genai_client=mock_genai,
            model_name="models/custom-embed",
            dimension=768,
            batch_size=16,
            max_retries=2,
            base_delay_seconds=0.1,
        )
        assert engine.supabase_client is mock_db
        assert engine.genai_client is mock_genai
        assert engine.model_name == "models/custom-embed"
        assert engine.dimension == 768
        assert engine.batch_size == 16

    def test_custom_exceptions(self):
        err = EmbeddingGenerationError(
            message="Failed to call model",
            model_name="models/gemini-embedding-001",
            details={"status": 429},
        )
        assert err.model_name == "models/gemini-embedding-001"
        assert err.details["status"] == 429
        assert "Failed to call model" in str(err)

        pipe_err = IngestionPipelineError(
            message="Upsert stage failed",
            stage="upsert_embeddings",
            details={"count": 5},
        )
        assert pipe_err.stage == "upsert_embeddings"
        assert pipe_err.details["count"] == 5


# =============================================================================
# 2. Embedding Generation & Dimensionality Tests
# =============================================================================

class TestEmbeddingGeneration:
    """Test suite for vector embedding generation and validation."""

    def test_empty_text_raises_value_error(self):
        engine = PolicyIngestionEngine(genai_client=MagicMock())
        with pytest.raises(ValueError, match="cannot be empty"):
            engine.generate_embedding("")

        with pytest.raises(ValueError, match="cannot be empty"):
            engine.generate_embedding("   \n\t  ")

    def test_generate_embedding_successful(self):
        mock_genai = MagicMock()
        mock_values = [0.123] * 768
        mock_response = MagicMock()
        mock_response.embeddings = [MagicMock(values=mock_values)]
        mock_genai.models.embed_content.return_value = mock_response

        engine = PolicyIngestionEngine(genai_client=mock_genai, dimension=768)
        vec = engine.generate_embedding("Test policy clause")

        assert len(vec) == 768
        assert vec[0] == 0.123
        mock_genai.models.embed_content.assert_called_once()

    def test_dimension_mismatch_triggers_retry_and_error(self):
        mock_genai = MagicMock()
        # Return 512 dimensions when 768 is expected
        mock_values = [0.1] * 512
        mock_response = MagicMock()
        mock_response.embeddings = [MagicMock(values=mock_values)]
        mock_genai.models.embed_content.return_value = mock_response

        engine = PolicyIngestionEngine(
            genai_client=mock_genai,
            dimension=768,
            max_retries=2,
            base_delay_seconds=0.01,
        )

        with pytest.raises(EmbeddingGenerationError, match="Failed to generate embedding"):
            engine.generate_embedding("Test text")

    def test_retry_mechanism_succeeds_on_second_attempt(self):
        mock_genai = MagicMock()
        mock_values = [0.05] * 768
        mock_success_response = MagicMock()
        mock_success_response.embeddings = [MagicMock(values=mock_values)]

        # Fail on first call, succeed on second call
        mock_genai.models.embed_content.side_effect = [
            RuntimeError("Rate limit 429"),
            mock_success_response,
        ]

        engine = PolicyIngestionEngine(
            genai_client=mock_genai,
            dimension=768,
            max_retries=3,
            base_delay_seconds=0.01,
        )

        vec = engine.generate_embedding("Text with retry")
        assert len(vec) == 768
        assert mock_genai.models.embed_content.call_count == 2


# =============================================================================
# 3. Payload Transformation & Chunk Embedding Tests
# =============================================================================

class TestChunkPayloadAssembly:
    """Test suite for converting DocumentChunks into database records."""

    def test_embed_chunks_structure(self):
        mock_genai = MagicMock()
        mock_values = [0.5] * 768
        mock_response = MagicMock()
        mock_response.embeddings = [MagicMock(values=mock_values)]
        mock_genai.models.embed_content.return_value = mock_response

        engine = PolicyIngestionEngine(genai_client=mock_genai, dimension=768)

        sample_chunks = [
            DocumentChunk(
                chunk_id="refund_policy_000",
                document_name="refund_policy.pdf",
                section_title="Eligibility",
                chunk_content="Refunds are eligible within 7 days.",
                word_count=6,
                char_length=35,
                metadata={"source_file": "refund_policy.pdf", "chunk_index": 0},
            ),
            DocumentChunk(
                chunk_id="refund_policy_001",
                document_name="refund_policy.pdf",
                section_title="Processing",
                chunk_content="Processing takes 5 to 7 business days.",
                word_count=7,
                char_length=38,
                metadata={"source_file": "refund_policy.pdf", "chunk_index": 1},
            ),
        ]

        records = engine.embed_chunks(sample_chunks)
        assert len(records) == 2

        assert records[0]["chunk_id"] == "refund_policy_000"
        assert records[0]["document_name"] == "refund_policy.pdf"
        assert records[0]["section_title"] == "Eligibility"
        assert len(records[0]["embedding"]) == 768
        assert records[0]["metadata"]["chunk_index"] == 0

        assert records[1]["chunk_id"] == "refund_policy_001"
        assert records[1]["section_title"] == "Processing"
        assert len(records[1]["embedding"]) == 768


# =============================================================================
# 4. Database Upsert & Verification Tests
# =============================================================================

class TestDatabaseUpsertAndVerification:
    """Test suite for Supabase upsert operations and verification queries."""

    def test_upsert_embeddings_idempotent_batching(self):
        mock_db = MagicMock()
        mock_query_builder = MagicMock()
        mock_query_builder.upsert.return_value = mock_query_builder
        mock_query_builder.execute.side_effect = [
            MagicMock(data=[{"chunk_id": "chunk_0"}, {"chunk_id": "chunk_1"}]),
            MagicMock(data=[{"chunk_id": "chunk_2"}, {"chunk_id": "chunk_3"}]),
            MagicMock(data=[{"chunk_id": "chunk_4"}]),
        ]
        mock_db.table.return_value = mock_query_builder

        engine = PolicyIngestionEngine(supabase_client=mock_db, batch_size=2)

        records = [
            {"chunk_id": f"chunk_{i}", "embedding": [0.1] * 768, "chunk_content": f"Text {i}"}
            for i in range(5)
        ]

        res = engine.upsert_embeddings(records)
        assert res["upserted_count"] == 5
        assert res["batches_processed"] == 3  # 2 + 2 + 1 = 3 batches
        assert len(res["chunk_ids"]) == 5
        assert mock_query_builder.upsert.call_count == 3

    def test_upsert_database_error_wrapped(self):
        mock_db = MagicMock()
        mock_query_builder = MagicMock()
        mock_query_builder.upsert.return_value = mock_query_builder
        mock_query_builder.execute.side_effect = RuntimeError("Supabase connection timeout")
        mock_db.table.return_value = mock_query_builder

        engine = PolicyIngestionEngine(supabase_client=mock_db)

        records = [{"chunk_id": "chunk_0", "embedding": [0.1] * 768}]
        with pytest.raises(DatabaseOperationError) as exc_info:
            engine.upsert_embeddings(records)

        assert exc_info.value.operation == "UPSERT"
        assert exc_info.value.table_name == "knowledge_embeddings"
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_verify_ingestion_valid_rows(self):
        mock_db = MagicMock()
        mock_query_builder = MagicMock()
        mock_query_builder.select.return_value = mock_query_builder
        mock_query_builder.execute.return_value = MagicMock(
            data=[
                {
                    "id": 1,
                    "chunk_id": "refund_policy_000",
                    "document_name": "refund_policy.pdf",
                    "section_title": "Eligibility",
                    "embedding": [0.01] * 768,
                    "metadata": {},
                },
                {
                    "id": 2,
                    "chunk_id": "shipping_policy_000",
                    "document_name": "shipping_policy.pdf",
                    "section_title": "Delivery",
                    "embedding": [0.02] * 768,
                    "metadata": {},
                },
            ]
        )
        mock_db.table.return_value = mock_query_builder

        engine = PolicyIngestionEngine(supabase_client=mock_db, dimension=768)
        verification = engine.verify_ingestion()

        assert verification["total_rows_verified"] == 2
        assert verification["vector_dimension_verified"] == 768
        assert verification["document_counts"]["refund_policy.pdf"] == 1
        assert verification["document_counts"]["shipping_policy.pdf"] == 1
        assert verification["is_valid"] is True

    def test_verify_ingestion_detects_corrupted_dimension(self):
        mock_db = MagicMock()
        mock_query_builder = MagicMock()
        mock_query_builder.select.return_value = mock_query_builder
        mock_query_builder.execute.return_value = MagicMock(
            data=[
                {
                    "id": 1,
                    "chunk_id": "corrupted_chunk_000",
                    "document_name": "refund_policy.pdf",
                    "embedding": [0.01] * 128,  # Invalid dimension
                }
            ]
        )
        mock_db.table.return_value = mock_query_builder

        engine = PolicyIngestionEngine(supabase_client=mock_db, dimension=768)
        with pytest.raises(AssertionError, match="invalid dimension 128"):
            engine.verify_ingestion()
