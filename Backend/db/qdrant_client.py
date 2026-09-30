"""Qdrant embedded vector client and collection manager for ResolveX RAG pipeline.

Provides local persistent vector indexing and fast HNSW cosine search.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_QDRANT_PATH = ROOT_DIR / "data" / "qdrant_storage"
DEFAULT_COLLECTION_NAME = "policy_documents"
DEFAULT_DIMENSION = 768

_qdrant_client_instance: QdrantClient | None = None


def get_qdrant_client(storage_path: Path | str | None = None) -> QdrantClient:
    """Returns singleton or newly connected Qdrant client instance."""
    global _qdrant_client_instance
    if _qdrant_client_instance is None:
        path = str(storage_path or DEFAULT_QDRANT_PATH)
        Path(path).mkdir(parents=True, exist_ok=True)
        _qdrant_client_instance = QdrantClient(path=path)
        logger.info("Initialized local persistent Qdrant client at: %s", path)
    return _qdrant_client_instance


def init_qdrant_collection(
    client: QdrantClient | None = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    dimension: int = DEFAULT_DIMENSION,
) -> None:
    """Initializes or ensures the specified Qdrant collection exists with cosine distance."""
    q_client = client or get_qdrant_client()
    if not q_client.collection_exists(collection_name):
        q_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        logger.info(
            "Created Qdrant collection '%s' with dimension %d and Cosine distance.",
            collection_name,
            dimension,
        )
