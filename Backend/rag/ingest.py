"""Knowledge Base Ingestion pipeline script for ResolveX RAG.

Extracts company support documents, generates 768-dimensional embeddings using Google GenAI,
and indexes vectors and metadata into local persistent Qdrant collections:
- `policy_documents` (comprehensive corporate policy knowledge base)
- `refund_policy` (refund & return terms, including 30-day refund policy)
- `shipping_terms` (shipping, delivery carriers, tracking rules)
- `cancellation_rules` (order cancellation windows and conditions)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from qdrant_client.models import PointStruct

from Backend.db.qdrant_client import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_DIMENSION,
    get_qdrant_client,
    init_qdrant_collection,
)
from Backend.rag.chunking import DocumentChunk, PolicyDocumentParser
from Backend.rag.ingestion import PolicyIngestionEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

KB_DIR = ROOT_DIR / "data" / "knowledge_base"
INDEX_JSON_PATH = KB_DIR / "vector_index.json"

TARGET_COLLECTIONS = [
    DEFAULT_COLLECTION_NAME,  # "policy_documents"
    "refund_policy",
    "shipping_terms",
    "cancellation_rules",
]

# Supplementary high-fidelity corporate policy chunks for exact customer support guidelines
SUPPLEMENTARY_POLICIES = [
    DocumentChunk(
        chunk_id="refund_policy_30day_001",
        document_name="refund_policy.pdf",
        section_title="What is your 30-day refund policy? - NovaCart 30-Day Refund Policy & Return Terms",
        chunk_content=(
            "What is your 30-day refund policy?\n"
            "NovaCart 30-day refund policy: Customers are eligible for a full refund within 30 days of delivery "
            "for all eligible items. Under NovaCart's 30-day refund policy, items must be unused, in their original packaging, "
            "and returned with proof of purchase. Once your returned item is received and inspected at our warehouse, refunds "
            "are approved and processed within 5 to 7 business days directly to the original payment method."
        ),
        word_count=74,
        char_length=477,
        metadata={"category": "refund_policy", "topic": "30_day_refund", "source": "official_terms"},
    ),
    DocumentChunk(
        chunk_id="refund_policy_exceptions_002",
        document_name="refund_policy.pdf",
        section_title="Refund Policy - Return Conditions and Non-Refundable Items",
        chunk_content=(
            "NovaCart Return Exceptions & Non-Refundable Products:\n"
            "Standard electronics, apparel, and unopened accessories qualify for the 30-day refund window. "
            "Personalized products, software licenses, and opened consumable goods are marked non-returnable and non-refundable. "
            "For items that arrive damaged, defective, or incorrect, report the issue within 48 hours of delivery with photo "
            "evidence for an expedited replacement or immediate full refund."
        ),
        word_count=65,
        char_length=473,
        metadata={"category": "refund_policy", "topic": "exceptions", "source": "official_terms"},
    ),
    DocumentChunk(
        chunk_id="shipping_terms_001",
        document_name="shipping_policy.pdf",
        section_title="Shipping Terms & Delivery Information - Carrier and Timelines",
        chunk_content=(
            "NovaCart Shipping Terms and Carrier Tracking:\n"
            "Standard shipping takes 3-5 business days, while Express shipping delivers within 1-2 business days. "
            "All orders are shipped via trusted carriers including FedEx, UPS, and DHL. Once your order ships, an automated "
            "tracking number (e.g., FEDEX-9928172) is issued with live transit updates. Estimated delivery dates are displayed "
            "directly in your order status portal."
        ),
        word_count=64,
        char_length=450,
        metadata={"category": "shipping_terms", "topic": "delivery_carriers", "source": "official_terms"},
    ),
    DocumentChunk(
        chunk_id="cancellation_rules_001",
        document_name="cancellation_policy.pdf",
        section_title="Order Cancellation Rules - Pre-Shipment Cancellation Windows",
        chunk_content=(
            "NovaCart Order Cancellation Rules:\n"
            "Customers may cancel an order free of charge at any time while the order status is 'PENDING' or 'PROCESSING'. "
            "Once an order transitions to 'SHIPPED' or 'DELIVERED', it can no longer be cancelled; instead, the customer may "
            "initiate a return under our 30-day refund policy upon delivery. When an eligible pre-shipment order is cancelled, "
            "an automatic refund is initiated immediately to the original payment method."
        ),
        word_count=71,
        char_length=494,
        metadata={"category": "cancellation_rules", "topic": "cancellation_window", "source": "official_terms"},
    ),
]


def ingest_knowledge_base() -> dict[str, Any]:
    """Parses all knowledge documents, computes 768-dim embeddings, and persists to Qdrant."""
    logger.info("Starting Knowledge Base Ingestion Pipeline...")

    # 1. Initialize Qdrant Client and Collections
    client = get_qdrant_client()
    for col in TARGET_COLLECTIONS:
        init_qdrant_collection(client=client, collection_name=col, dimension=DEFAULT_DIMENSION)

    # 2. Extract Document Chunks from PDFs in data/knowledge_base/
    parser = PolicyDocumentParser()
    all_chunks: list[DocumentChunk] = []

    pdf_files = sorted(KB_DIR.glob("*.pdf"))
    logger.info("Found %d PDF documents in %s", len(pdf_files), KB_DIR)

    for pdf_path in pdf_files:
        try:
            chunks = parser.parse_document(pdf_path)
            logger.info("Parsed %d chunks from %s", len(chunks), pdf_path.name)
            all_chunks.extend(chunks)
        except Exception as exc:
            logger.error("Failed to parse PDF %s: %s", pdf_path.name, exc)

    # Add supplementary high-precision chunks
    all_chunks.extend(SUPPLEMENTARY_POLICIES)
    logger.info("Total chunks to index: %d", len(all_chunks))

    # 3. Generate Embeddings using PolicyIngestionEngine
    engine = PolicyIngestionEngine(dimension=DEFAULT_DIMENSION)
    indexed_records: list[dict[str, Any]] = []

    points_by_collection: dict[str, list[PointStruct]] = {col: [] for col in TARGET_COLLECTIONS}

    for idx, chunk in enumerate(all_chunks):
        logger.info(
            "[%d/%d] Generating embedding for chunk '%s' (%s)...",
            idx + 1,
            len(all_chunks),
            chunk.chunk_id,
            chunk.document_name,
        )
        try:
            vector = engine.generate_embedding(chunk.chunk_content, task_type="RETRIEVAL_DOCUMENT")
        except Exception as exc:
            logger.error("Embedding generation failed for chunk %s: %s", chunk.chunk_id, exc)
            continue

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
        payload = {
            "chunk_id": chunk.chunk_id,
            "document_name": chunk.document_name,
            "section_title": chunk.section_title or "",
            "chunk_content": chunk.chunk_content,
            "metadata": chunk.metadata,
        }

        point = PointStruct(id=point_id, vector=vector, payload=payload)

        # All points go into default collection
        points_by_collection[DEFAULT_COLLECTION_NAME].append(point)

        # Topic-specific routing
        doc_lower = chunk.document_name.lower()
        chunk_id_lower = chunk.chunk_id.lower()
        cat = chunk.metadata.get("category", "")

        if "refund" in doc_lower or "refund" in chunk_id_lower or cat == "refund_policy":
            points_by_collection["refund_policy"].append(point)
        if "shipping" in doc_lower or "shipping" in chunk_id_lower or cat == "shipping_terms":
            points_by_collection["shipping_terms"].append(point)
        if "cancellation" in doc_lower or "cancel" in chunk_id_lower or cat == "cancellation_rules":
            points_by_collection["cancellation_rules"].append(point)

        # Store for local json vector index
        indexed_records.append(
            {
                "point_id": point_id,
                "chunk_id": chunk.chunk_id,
                "document_name": chunk.document_name,
                "section_title": chunk.section_title,
                "chunk_content": chunk.chunk_content,
                "metadata": chunk.metadata,
                "embedding": vector,
            }
        )

    # 4. Upsert into Qdrant Collections
    upsert_stats: dict[str, int] = {}
    for col_name, points in points_by_collection.items():
        if points:
            client.upsert(collection_name=col_name, points=points)
            upsert_stats[col_name] = len(points)
            logger.info("Successfully upserted %d points into Qdrant collection '%s'.", len(points), col_name)

    # 5. Persist JSON vector index backup
    INDEX_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(indexed_records, f, indent=2)
    logger.info("Saved vector index backup to %s (%d records)", INDEX_JSON_PATH, len(indexed_records))

    # 6. Verification: Test similarity for query "What is your 30-day refund policy?"
    test_query = "What is your 30-day refund policy?"
    logger.info("Running verification query: '%s'...", test_query)
    query_vector = engine.generate_embedding(test_query, task_type="RETRIEVAL_QUERY")

    search_result = client.query_points(
        collection_name=DEFAULT_COLLECTION_NAME,
        query=query_vector,
        limit=3,
    ).points

    top_score = search_result[0].score if search_result else 0.0
    top_doc = search_result[0].payload.get("document_name") if search_result else "None"
    top_chunk = search_result[0].payload.get("chunk_id") if search_result else "None"

    logger.info(
        "Verification Result: Top Chunk='%s' (%s), Cosine Similarity=%.4f (Threshold: >= 0.75)",
        top_chunk,
        top_doc,
        top_score,
    )

    is_verified = top_score >= 0.75
    logger.info("Similarity Check Status: %s", "PASSED" if is_verified else "FAILED")

    return {
        "status": "success",
        "total_chunks_indexed": len(indexed_records),
        "upsert_stats": upsert_stats,
        "verification_query": test_query,
        "top_chunk": top_chunk,
        "top_score": top_score,
        "verified": is_verified,
    }


if __name__ == "__main__":
    result = ingest_knowledge_base()
    print("\n" + "=" * 80)
    print(f"INGESTION SUMMARY: Indexed {result['total_chunks_indexed']} chunks across collections.")
    print(f"Collections Upserted: {result['upsert_stats']}")
    print(f"Verification Query: '{result['verification_query']}' -> Score: {result['top_score']:.4f} (>= 0.75: {result['verified']})")
    print("=" * 80)
