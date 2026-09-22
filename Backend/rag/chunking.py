"""Knowledge document parsing, semantic chunking, and provenance metadata binding for ResolveX RAG pipeline.

Step 5 — Phase 1: Knowledge Document Parsing, Semantic Chunking & Provenance Metadata Binding.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
import pypdf


class DocumentChunk(BaseModel):
    """Represents an extracted, chunked segment of a knowledge base document with full provenance metadata."""

    chunk_id: str = Field(..., description="Unique deterministic identifier for the chunk (e.g., 'refund_policy_000')")
    document_name: str = Field(..., description="Source document file name (e.g., 'refund_policy.pdf')")
    section_title: str | None = Field(default=None, description="Extracted section heading or document topic")
    chunk_content: str = Field(..., description="Normalized text content of the chunk")
    word_count: int = Field(..., description="Total number of whitespace-delimited words in the chunk")
    char_length: int = Field(..., description="Total character length of the chunk content")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Provenance, windowing, and parsing metadata")

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


def chunk_text(text: str, target_words: int = 120, overlap_words: int = 30) -> list[str]:
    """Splits text into chunks using a sliding word window with specified overlap.

    Args:
        text: Raw or cleaned input text string.
        target_words: Target number of words per chunk (default: 120).
        overlap_words: Number of overlapping words between consecutive chunks (default: 30).

    Returns:
        List of text chunk strings.

    Arithmetic & Sliding Window Mechanics:
        - If total words N <= target_words: returns a single chunk containing all words.
        - If total words N > target_words:
            Step size = max(1, target_words - overlap_words) = 120 - 30 = 90 words.
            Chunk 0: words[0 : 120] (contains words 0..119)
            Chunk 1: words[90 : 210] (contains words 90..209, overlapping words 90..119 from Chunk 0)
            Chunk k: words[k * 90 : min(k * 90 + 120, N)]
            Overlap count between Chunk k and Chunk k+1 = exactly 30 words (or remaining words).
    """
    if not text or not text.strip():
        return []

    words = text.strip().split()
    total_words = len(words)

    if total_words <= target_words:
        return [" ".join(words)]

    step = max(1, target_words - overlap_words)
    chunks: list[str] = []

    for start_idx in range(0, total_words, step):
        end_idx = min(start_idx + target_words, total_words)
        chunk_words = words[start_idx:end_idx]
        if chunk_words:
            chunks.append(" ".join(chunk_words))
        if end_idx >= total_words:
            break

    return chunks


class PolicyDocumentParser:
    """Extracts, cleans, and chunks corporate policy documents (PDFs) with provenance metadata binding."""

    SUPPORTED_DOCUMENTS = (
        "refund_policy.pdf",
        "cancellation_policy.pdf",
        "shipping_policy.pdf",
        "payment_policy.pdf",
        "account_policy.pdf",
        "faq.pdf",
        "support_guidelines.pdf",
    )

    DOCUMENT_TITLES = {
        "refund_policy.pdf": "Refund Policy",
        "cancellation_policy.pdf": "Cancellation Policy",
        "shipping_policy.pdf": "Shipping & Delivery Policy",
        "payment_policy.pdf": "Payment Policy",
        "account_policy.pdf": "Account & Privacy Support Policy",
        "faq.pdf": "Frequently Asked Questions (FAQ)",
        "support_guidelines.pdf": "Customer Support Guidelines",
    }

    KNOWN_SECTIONS = [
        "Account Assistance",
        "Security",
        "Privacy",
        "Escalation",
        "Before Shipment",
        "After Shipment",
        "Confirmation",
        "General",
        "Orders",
        "Payments",
        "Refunds and Cancellations",
        "Account",
        "Payment Verification",
        "Failed Payments",
        "Payment Deducted but Order Missing",
        "Payment Deducted but Order Failed",
        "Refunds",
        "Eligibility",
        "Refund Processing",
        "Exceptions",
        "Shipping",
        "Delivery Status",
        "Delayed Delivery",
        "Address",
        "Support Principles",
        "Missing Information",
        "Tool Failures",
        "Human Escalation",
        "Conversation Context",
    ]

    def extract_text_from_pdf(self, pdf_path: str | Path) -> str:
        """Reads a PDF file using pypdf and extracts concatenated raw text across all pages.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            Extracted raw text string.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            ValueError: If the PDF contains no readable text or fails to parse.
        """
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"Policy document not found at: {path}")

        try:
            reader = pypdf.PdfReader(str(path))
            pages_text: list[str] = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    pages_text.append(extracted)
            if not pages_text:
                raise ValueError(f"No extractable text found in PDF: {path.name}")
            return "\n\n".join(pages_text)
        except Exception as exc:
            if isinstance(exc, (FileNotFoundError, ValueError)):
                raise
            raise ValueError(f"Failed to extract text from PDF '{path.name}': {exc}") from exc

    def clean_text(self, raw_text: str) -> str:
        """Cleans extracted PDF text by normalizing whitespace, standardizing line breaks,
        handling unicode replacements and control bullet characters.

        Args:
            raw_text: Raw string extracted from PDF.

        Returns:
            Cleaned and normalized text string.
        """
        if not raw_text:
            return ""

        # Normalize line endings
        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

        # Replace non-printable ASCII control characters / bullet symbols (e.g. \x7f, \x00-\x08, \x0b-\x1f)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "- ", text)

        # Normalize unicode replacement character (\ufffd) to hyphen
        text = text.replace("\ufffd", "-")

        # Normalize em-dash and en-dash to hyphen with spacing
        text = text.replace("\u2014", " - ").replace("\u2013", " - ")

        # Clean horizontal whitespace on each line
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]

        # Recombine and collapse 3+ consecutive newlines into double newlines
        cleaned = "\n".join(lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return cleaned.strip()

    def detect_section_title(self, chunk_text_content: str, document_name: str) -> str | None:
        """Extracts or infers a section title or heading for a given chunk of policy text.

        Args:
            chunk_text_content: The text of the chunk.
            document_name: The filename of the document.

        Returns:
            Detected section title or standard document title.
        """
        default_doc_title = self.DOCUMENT_TITLES.get(
            document_name,
            Path(document_name).stem.replace("_", " ").title(),
        )

        # Check if any known section heading is present in this chunk
        for section in self.KNOWN_SECTIONS:
            # Match section title as standalone header or after bullet / title
            pattern = rf"(?:^|\b){re.escape(section)}(?:\b|$)"
            if re.search(pattern, chunk_text_content, re.IGNORECASE):
                return f"{default_doc_title} - {section}"

        return default_doc_title

    def parse_document(
        self,
        pdf_path: str | Path,
        target_words: int = 120,
        overlap_words: int = 30,
    ) -> list[DocumentChunk]:
        """Parses a single policy PDF, cleaning the text, chunking with sliding-window overlap,
        and binding full provenance metadata.

        Args:
            pdf_path: Path to the policy PDF.
            target_words: Target word count per chunk.
            overlap_words: Word overlap between consecutive chunks.

        Returns:
            List of DocumentChunk instances.
        """
        path = Path(pdf_path)
        raw_text = self.extract_text_from_pdf(path)
        cleaned_text = self.clean_text(raw_text)

        if not cleaned_text:
            return []

        text_chunks = chunk_text(cleaned_text, target_words=target_words, overlap_words=overlap_words)
        total_chunks = len(text_chunks)
        doc_stem = path.stem
        step = max(1, target_words - overlap_words)

        document_chunks: list[DocumentChunk] = []
        for idx, chunk_str in enumerate(text_chunks):
            chunk_id = f"{doc_stem}_{idx:03d}"
            words = chunk_str.split()
            word_count = len(words)
            char_length = len(chunk_str)
            section_title = self.detect_section_title(chunk_str, path.name)

            start_word_index = idx * step
            end_word_index = start_word_index + word_count

            metadata: dict[str, Any] = {
                "source_file": path.name,
                "source_path": str(path.as_posix()),
                "chunk_index": idx,
                "total_chunks": total_chunks,
                "target_words": target_words,
                "overlap_words": overlap_words,
                "start_word_index": start_word_index,
                "end_word_index": end_word_index,
                "document_stem": doc_stem,
            }

            document_chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_name=path.name,
                    section_title=section_title,
                    chunk_content=chunk_str,
                    word_count=word_count,
                    char_length=char_length,
                    metadata=metadata,
                )
            )

        return document_chunks

    def parse_directory(
        self,
        directory_path: str | Path = "data/knowledge_base",
        target_words: int = 120,
        overlap_words: int = 30,
    ) -> list[DocumentChunk]:
        """Parses all policy documents in the specified knowledge base directory.

        Args:
            directory_path: Path to the directory containing policy PDFs.
            target_words: Target word count per chunk.
            overlap_words: Word overlap between consecutive chunks.

        Returns:
            Flat list of all DocumentChunk instances across all documents.

        Raises:
            FileNotFoundError: If the directory does not exist.
        """
        dir_path = Path(directory_path)
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Knowledge base directory not found at: {dir_path}")

        all_chunks: list[DocumentChunk] = []
        pdf_files = sorted(dir_path.glob("*.pdf"))

        for pdf_file in pdf_files:
            chunks = self.parse_document(
                pdf_file,
                target_words=target_words,
                overlap_words=overlap_words,
            )
            all_chunks.extend(chunks)

        return all_chunks

    def parse_all_policies(
        self,
        directory_path: str | Path = "data/knowledge_base",
        target_words: int = 120,
        overlap_words: int = 30,
    ) -> dict[str, list[DocumentChunk]]:
        """Parses all 7 standard policy documents and groups chunks by document name.

        Args:
            directory_path: Path to knowledge base directory.
            target_words: Target words per chunk.
            overlap_words: Overlap words between chunks.

        Returns:
            Dictionary mapping document filename to its list of DocumentChunks.
        """
        dir_path = Path(directory_path)
        if not dir_path.is_dir():
            raise FileNotFoundError(f"Knowledge base directory not found at: {dir_path}")

        policy_map: dict[str, list[DocumentChunk]] = {}
        for doc_name in self.SUPPORTED_DOCUMENTS:
            file_path = dir_path / doc_name
            if file_path.is_file():
                policy_map[doc_name] = self.parse_document(
                    file_path,
                    target_words=target_words,
                    overlap_words=overlap_words,
                )
        return policy_map
