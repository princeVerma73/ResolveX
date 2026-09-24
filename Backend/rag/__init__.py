"""ResolveX RAG (Retrieval-Augmented Generation) package.

Provides knowledge document parsing, semantic chunking, embedding generation,
and hybrid vector retrieval modules.
"""

from Backend.rag.chunking import (
    DocumentChunk,
    PolicyDocumentParser,
    chunk_text,
)
from Backend.rag.ingestion import (
    EmbeddingGenerationError,
    IngestionPipelineError,
    PolicyIngestionEngine,
)
from Backend.rag.generation import (
    EvaluationResult,
    EvidenceEvaluator,
    GroundedPromptAssembler,
    GroundedResponse,
    ResolutionGenerator,
)
from Backend.rag.reranking import (
    CrossEncoderReranker,
    RankedChunk,
    reciprocal_rank_fusion,
)
from Backend.rag.retrieval import (
    HybridRetriever,
    RetrievalError,
    RetrievedChunk,
)

__all__ = [
    "DocumentChunk",
    "chunk_text",
    "PolicyDocumentParser",
    "PolicyIngestionEngine",
    "EmbeddingGenerationError",
    "IngestionPipelineError",
    "HybridRetriever",
    "RetrievedChunk",
    "RetrievalError",
    "RankedChunk",
    "reciprocal_rank_fusion",
    "CrossEncoderReranker",
    "EvaluationResult",
    "GroundedResponse",
    "EvidenceEvaluator",
    "GroundedPromptAssembler",
    "ResolutionGenerator",
]



