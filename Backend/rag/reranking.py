"""Reciprocal Rank Fusion (RRF) and Cross-Encoder Re-Ranking Engine for ResolveX RAG pipeline.

Step 5 — Phase 4: Reciprocal Rank Fusion & Cross-Encoder Re-Ranking.

WHAT:
    A two-stage re-ranking pipeline:
    1. Reciprocal Rank Fusion (RRF): Merges Dense and Sparse candidate lists (up to 40 chunks)
       into an integrated, deduplicated top-20 candidate pool using rank-based reciprocal scoring.
    2. Cross-Encoder Re-Ranking: Uses FlashRank (ONNX-powered `ms-marco-TinyBERT-L-2-v2`) to perform
       all-to-all query-passage cross-attention, distilling candidates into the definitive Top-3 chunks.

WHY:
    - Eliminates score distribution mismatch between cosine similarity and full-text cover density.
    - Overcomes Bi-Encoder expressivity ceilings with deep token-level cross-attention.
    - Prevents LLM context dilution ("Lost in the Middle") by feeding strictly top-3 verified context.
    - Sub-15ms CPU inference via ONNX Runtime with zero PyTorch / GPU overhead.

HOW:
    1. `reciprocal_rank_fusion(dense_results, sparse_results, k=60, top_n=20)`:
       Computes RRF score for each unique chunk_id: Score(d) = sum(1 / (k + rank_m(d))).
    2. `CrossEncoderReranker.rerank(query, candidates, top_k=3)`:
       Passes query and candidate passages into FlashRank ONNX model, sorts by cross-attention
       score descending, and outputs typed `RankedChunk` models with `final_rank`.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import BaseModel, Field

from Backend.rag.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

# Default RRF smoothing constant (TREC standard)
DEFAULT_RRF_K = 60
DEFAULT_RRF_TOP_N = 20
DEFAULT_FINAL_TOP_K = 3
DEFAULT_RERANK_MODEL = "ms-marco-TinyBERT-L-2-v2"


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

class RankedChunk(BaseModel):
    """Domain model representing a final cross-encoder ranked policy chunk.

    Attributes:
        chunk_id: Unique deterministic identifier for the chunk.
        document_name: Source PDF policy filename.
        section_title: Section header or title.
        chunk_content: Clean text body of the chunk.
        score: Primary relevance score from cross-encoder.
        retrieval_type: Originating retrieval branch or 'hybrid'.
        rrf_score: Intermediate Reciprocal Rank Fusion score.
        rerank_score: FlashRank cross-encoder relevance score.
        final_rank: 1-indexed position in final ranking (1 = most relevant).
    """

    chunk_id: str = Field(..., description="Unique chunk ID")
    document_name: str = Field(..., description="Source policy filename")
    section_title: str | None = Field(default=None, description="Section title")
    chunk_content: str = Field(..., description="Chunk text content")
    score: float = Field(..., description="Primary relevance score")
    retrieval_type: Literal["dense", "sparse", "hybrid"] = Field(
        default="hybrid", description="Originating retrieval type"
    )
    rrf_score: float = Field(..., description="Reciprocal Rank Fusion score")
    rerank_score: float = Field(..., description="Cross-encoder relevance score")
    final_rank: int = Field(..., ge=1, description="1-indexed rank position (1..K)")


# -----------------------------------------------------------------------------
# Stage 1: Reciprocal Rank Fusion (RRF)
# -----------------------------------------------------------------------------

def reciprocal_rank_fusion(
    dense_results: Sequence[RetrievedChunk],
    sparse_results: Sequence[RetrievedChunk],
    k: int = DEFAULT_RRF_K,
    top_n: int = DEFAULT_RRF_TOP_N,
) -> list[RetrievedChunk]:
    """Fuses and deduplicates dense and sparse candidate lists using Reciprocal Rank Fusion.

    WHAT:
        Merges two ranked candidate lists into a single consolidated ranking based on reciprocal
        rank positions rather than raw incommensurable scores.

    WHY:
        - Dense similarity scores (0..1) and Sparse cover-density scores (0..inf) cannot be
          meaningfully normalized or linearly combined without distortion.
        - RRF balances lists without score calibration and promotes candidates appearing in both.

    HOW:
        Formula:
            RRF_Score(d) = sum_{m in {dense, sparse}} (1 / (k + rank_m(d)))
        where rank_m(d) is the 1-based index of document d in list m.

    Args:
        dense_results: Ordered list of dense retrieval chunks.
        sparse_results: Ordered list of sparse retrieval chunks.
        k: Smoothing ranking constant (default: 60).
        top_n: Maximum number of merged candidates to return (default: 20).

    Returns:
        List of deduplicated `RetrievedChunk` instances sorted by RRF score descending.
    """
    if k < 0:
        raise ValueError(f"RRF parameter k must be non-negative, got {k}.")
    if top_n <= 0:
        return []

    # Map chunk_id -> {"chunk": RetrievedChunk, "rrf_score": float, "sources": set}
    merged_data: dict[str, dict[str, Any]] = {}

    # Process Dense Stream (1-indexed ranks)
    for rank_idx, chunk in enumerate(dense_results, start=1):
        rrf_increment = 1.0 / (k + rank_idx)
        if chunk.chunk_id not in merged_data:
            merged_data[chunk.chunk_id] = {
                "chunk": chunk,
                "rrf_score": rrf_increment,
                "sources": {"dense"},
            }
        else:
            merged_data[chunk.chunk_id]["rrf_score"] += rrf_increment
            merged_data[chunk.chunk_id]["sources"].add("dense")

    # Process Sparse Stream (1-indexed ranks)
    for rank_idx, chunk in enumerate(sparse_results, start=1):
        rrf_increment = 1.0 / (k + rank_idx)
        if chunk.chunk_id not in merged_data:
            merged_data[chunk.chunk_id] = {
                "chunk": chunk,
                "rrf_score": rrf_increment,
                "sources": {"sparse"},
            }
        else:
            merged_data[chunk.chunk_id]["rrf_score"] += rrf_increment
            merged_data[chunk.chunk_id]["sources"].add("sparse")

    if not merged_data:
        return []

    # Sort candidates by combined RRF score descending
    sorted_items = sorted(
        merged_data.values(),
        key=lambda item: item["rrf_score"],
        reverse=True,
    )

    # Format output RetrievedChunk objects with updated rrf_score
    fused_chunks: list[RetrievedChunk] = []
    for item in sorted_items[:top_n]:
        base_chunk = item["chunk"]
        sources = item["sources"]
        retrieval_type: Literal["dense", "sparse"] = (
            "dense" if sources == {"dense"} else ("sparse" if sources == {"sparse"} else "dense")
        )
        # Construct updated RetrievedChunk with rrf_score
        updated_chunk = RetrievedChunk(
            chunk_id=base_chunk.chunk_id,
            document_name=base_chunk.document_name,
            section_title=base_chunk.section_title,
            chunk_content=base_chunk.chunk_content,
            score=round(item["rrf_score"], 6),
            retrieval_type=retrieval_type,
        )
        fused_chunks.append(updated_chunk)

    return fused_chunks


# -----------------------------------------------------------------------------
# Stage 2: Cross-Encoder Re-Ranker (FlashRank)
# -----------------------------------------------------------------------------

class CrossEncoderReranker:
    """FlashRank-powered Cross-Encoder Re-Ranker for high-precision context filtering.

    WHAT:
        Applies a local ONNX cross-attention transformer model to jointly evaluate
        `[query, passage]` token pairs and output fine-grained relevance logits.

    WHY:
        - Bi-encoders lack inter-token cross-attention.
        - Distills a top-20 candidate pool down to the highest-confidence top-3 chunks.
        - ONNX runtime executes on CPU in <15ms with zero PyTorch dependencies.

    HOW:
        - Uses FlashRank `Ranker` (`ms-marco-TinyBERT-L-2-v2`).
        - Builds `RerankRequest` payloads and extracts softmax relevance scores.
        - Wraps scored items into typed `RankedChunk` objects with `final_rank` bindings.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_RERANK_MODEL,
        max_length: int = 512,
        cache_dir: str | None = None,
    ) -> None:
        """Initialize the Cross-Encoder Re-Ranker.

        Args:
            model_name: FlashRank model identifier (default: 'ms-marco-TinyBERT-L-2-v2').
            max_length: Maximum token sequence length for cross-attention.
            cache_dir: Optional custom model cache directory.
        """
        self.model_name = model_name
        self.max_length = max_length
        self.cache_dir = cache_dir
        self._ranker: Any | None = None

    @property
    def ranker(self) -> Any:
        """Lazy initializer for FlashRank Ranker client."""
        if self._ranker is None:
            try:
                from flashrank import Ranker
                kwargs: dict[str, Any] = {"model_name": self.model_name, "max_length": self.max_length}
                if self.cache_dir:
                    kwargs["cache_dir"] = self.cache_dir
                self._ranker = Ranker(**kwargs)
                logger.info("Initialized FlashRank Ranker with model '%s'.", self.model_name)
            except Exception as exc:
                logger.error("Failed to initialize FlashRank Ranker: %s", exc)
                raise
        return self._ranker

    def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievedChunk],
        top_k: int = DEFAULT_FINAL_TOP_K,
    ) -> list[RankedChunk]:
        """Re-ranks candidate chunks using cross-attention and returns the top-K passages.

        WHAT:
            Jointly scores query-candidate pairs using full cross-attention transformer layers.

        WHY:
            Maximizes grounding accuracy for downstream reasoning LLMs by filtering out false-positive
            lexical/vector matches.

        HOW:
            1. Validates non-empty query and non-empty candidates.
            2. Formats passages payload for FlashRank `RerankRequest`.
            3. Calls `self.ranker.rerank(request)`.
            4. Maps scored results to `RankedChunk` models with 1-based `final_rank`.

        Args:
            query: User or agent question string.
            candidates: Pool of candidate chunks (typically from RRF top-20).
            top_k: Number of final ranked chunks to return (default: 3).

        Returns:
            List of `RankedChunk` instances sorted by `rerank_score` descending (top 1..K).

        Raises:
            ValueError: If query is empty or whitespace-only.
        """
        if not query or not query.strip():
            raise ValueError("Query string for reranking cannot be empty.")

        if not candidates:
            return []

        clean_query = query.strip()
        effective_top_k = max(1, min(top_k, len(candidates)))

        # Build candidate lookup dictionary to preserve provenance & RRF score
        candidate_lookup = {chunk.chunk_id: chunk for chunk in candidates}

        # Format FlashRank payload
        passages: list[dict[str, Any]] = []
        for chunk in candidates:
            passages.append(
                {
                    "id": chunk.chunk_id,
                    "text": chunk.chunk_content,
                    "meta": {
                        "document_name": chunk.document_name,
                        "section_title": chunk.section_title,
                        "rrf_score": chunk.score,
                    },
                }
            )

        try:
            from flashrank import RerankRequest

            request = RerankRequest(query=clean_query, passages=passages)
            ranked_results = self.ranker.rerank(request)

        except Exception as exc:
            logger.warning(
                "FlashRank cross-encoder inference failed (%s); falling back to RRF ordering.",
                exc,
            )
            # Fallback to candidates sorted by RRF score
            ranked_chunks: list[RankedChunk] = []
            for rank_idx, chunk in enumerate(candidates[:effective_top_k], start=1):
                ranked_chunks.append(
                    RankedChunk(
                        chunk_id=chunk.chunk_id,
                        document_name=chunk.document_name,
                        section_title=chunk.section_title,
                        chunk_content=chunk.chunk_content,
                        score=chunk.score,
                        retrieval_type="hybrid",
                        rrf_score=chunk.score,
                        rerank_score=chunk.score,
                        final_rank=rank_idx,
                    )
                )
            return ranked_chunks

        # Process FlashRank outputs
        final_ranked_chunks: list[RankedChunk] = []
        for rank_idx, res in enumerate(ranked_results[:effective_top_k], start=1):
            chunk_id = str(res["id"])
            rerank_score = float(res.get("score", 0.0))
            orig_chunk = candidate_lookup.get(chunk_id)

            if orig_chunk is not None:
                doc_name = orig_chunk.document_name
                section_title = orig_chunk.section_title
                content = orig_chunk.chunk_content
                rrf_score = orig_chunk.score
            else:
                meta = res.get("meta", {})
                doc_name = str(meta.get("document_name", "unknown"))
                section_title = meta.get("section_title")
                content = str(res.get("text", ""))
                rrf_score = float(meta.get("rrf_score", 0.0))

            ranked_chunk = RankedChunk(
                chunk_id=chunk_id,
                document_name=doc_name,
                section_title=section_title,
                chunk_content=content,
                score=round(rerank_score, 6),
                retrieval_type="hybrid",
                rrf_score=round(rrf_score, 6),
                rerank_score=round(rerank_score, 6),
                final_rank=rank_idx,
            )
            final_ranked_chunks.append(ranked_chunk)

        return final_ranked_chunks
