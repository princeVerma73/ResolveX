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

__all__ = [
    "DocumentChunk",
    "chunk_text",
    "PolicyDocumentParser",
    "PolicyIngestionEngine",
    "EmbeddingGenerationError",
    "IngestionPipelineError",
]
