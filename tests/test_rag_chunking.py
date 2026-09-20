"""Unit test suite for ResolveX RAG Document Parsing & Semantic Chunking (Step 5 — Phase 1).

Validates:
1. DocumentChunk Pydantic model validation and metadata binding.
2. chunk_text() sliding-window word splitting and arithmetic overlap.
3. PolicyDocumentParser text extraction, cleaning, and section title detection.
4. Parsing of all 7 knowledge base PDFs in data/knowledge_base/.
5. Boundary overlap and provenance metadata integrity.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError

from Backend.rag.chunking import (
    DocumentChunk,
    PolicyDocumentParser,
    chunk_text,
)

KNOWLEDGE_BASE_DIR = Path("data/knowledge_base")
EXPECTED_PDF_FILES = [
    "account_policy.pdf",
    "cancellation_policy.pdf",
    "faq.pdf",
    "payment_policy.pdf",
    "refund_policy.pdf",
    "shipping_policy.pdf",
    "support_guidelines.pdf",
]


class TestDocumentChunkModel:
    """Tests DocumentChunk Pydantic model behavior, serialization, and validation."""

    def test_document_chunk_valid_instantiation(self):
        chunk = DocumentChunk(
            chunk_id="refund_policy_000",
            document_name="refund_policy.pdf",
            section_title="Refund Policy - Eligibility",
            chunk_content="Eligible products may be returned within 7 calendar days.",
            word_count=8,
            char_length=57,
            metadata={"source": "data/knowledge_base/refund_policy.pdf", "chunk_index": 0},
        )
        assert chunk.chunk_id == "refund_policy_000"
        assert chunk.document_name == "refund_policy.pdf"
        assert chunk.section_title == "Refund Policy - Eligibility"
        assert chunk.word_count == 8
        assert chunk.char_length == 57
        assert chunk.metadata["chunk_index"] == 0

    def test_document_chunk_missing_required_fields_raises_validation_error(self):
        with pytest.raises(ValidationError):
            # Missing chunk_content, word_count, char_length
            DocumentChunk(
                chunk_id="test_000",
                document_name="test.pdf",
            )

    def test_document_chunk_whitespace_stripping(self):
        chunk = DocumentChunk(
            chunk_id="  test_000  ",
            document_name=" test.pdf ",
            section_title="  Section 1  ",
            chunk_content="  Sample text content.  ",
            word_count=3,
            char_length=20,
        )
        assert chunk.chunk_id == "test_000"
        assert chunk.document_name == "test.pdf"
        assert chunk.section_title == "Section 1"
        assert chunk.chunk_content == "Sample text content."


class TestSlidingWindowChunkText:
    """Tests chunk_text() sliding-window word splitting, step arithmetic, and boundary overlaps."""

    def test_empty_and_whitespace_text_returns_empty_list(self):
        assert chunk_text("") == []
        assert chunk_text("   \n\t  ") == []

    def test_text_within_target_words_returns_single_chunk(self):
        text = "This is a brief policy statement with only eight words."
        chunks = chunk_text(text, target_words=120, overlap_words=30)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_sliding_window_arithmetic_and_exact_overlap(self):
        # Generate synthetic 200-word text: "word_000 word_001 ... word_199"
        total_word_count = 200
        words = [f"word_{i:03d}" for i in range(total_word_count)]
        text = " ".join(words)

        target_words = 120
        overlap_words = 30
        step = target_words - overlap_words  # 90

        chunks = chunk_text(text, target_words=target_words, overlap_words=overlap_words)

        # Expected chunks:
        # Chunk 0: words 0..119 (120 words)
        # Chunk 1: words 90..199 (110 words)
        assert len(chunks) == 2

        chunk_0_words = chunks[0].split()
        chunk_1_words = chunks[1].split()

        assert len(chunk_0_words) == 120
        assert chunk_0_words[0] == "word_000"
        assert chunk_0_words[-1] == "word_119"

        assert len(chunk_1_words) == 110
        assert chunk_1_words[0] == "word_090"
        assert chunk_1_words[-1] == "word_199"

        # Overlap verification: The last 30 words of Chunk 0 must equal the first 30 words of Chunk 1
        overlap_from_chunk_0 = chunk_0_words[-30:]
        overlap_from_chunk_1 = chunk_1_words[:30]
        assert overlap_from_chunk_0 == overlap_from_chunk_1
        assert overlap_from_chunk_0[0] == "word_090"
        assert overlap_from_chunk_0[-1] == "word_119"

    def test_custom_window_parameters(self):
        # 25 words with target=10, overlap=3 -> step = 7
        # Chunk 0: words 0..9 (10 words)
        # Chunk 1: words 7..16 (10 words)
        # Chunk 2: words 14..23 (10 words)
        # Chunk 3: words 21..24 (4 words)
        words = [f"w{i}" for i in range(25)]
        text = " ".join(words)
        chunks = chunk_text(text, target_words=10, overlap_words=3)

        assert len(chunks) == 4
        assert len(chunks[0].split()) == 10
        assert len(chunks[1].split()) == 10
        assert len(chunks[2].split()) == 10
        assert len(chunks[3].split()) == 4

        # Verify overlap between chunk 1 and chunk 2 (3 words: w14, w15, w16)
        c1_words = chunks[1].split()
        c2_words = chunks[2].split()
        assert c1_words[-3:] == c2_words[:3]
        assert c2_words[:3] == ["w14", "w15", "w16"]


class TestPolicyDocumentParser:
    """Tests PolicyDocumentParser extraction, cleaning, section detection, and batch directory parsing."""

    def setup_method(self):
        self.parser = PolicyDocumentParser()

    def test_clean_text_normalizes_control_chars_and_formatting(self):
        raw_text = "NovaCart \u2014 Policy\r\n\x7f Point 1\n\x7f Point 2\n\n\n\n\ufffd Damaged item\t\twith spaces  \n"
        cleaned = self.parser.clean_text(raw_text)

        assert "\r" not in cleaned
        assert "\x7f" not in cleaned
        assert "\ufffd" not in cleaned
        assert "\n\n\n" not in cleaned
        assert "- Point 1" in cleaned
        assert "- Point 2" in cleaned
        assert "- Damaged item with spaces" in cleaned

    def test_missing_pdf_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.parser.extract_text_from_pdf("data/knowledge_base/non_existent_policy.pdf")

    def test_missing_directory_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.parser.parse_directory("data/non_existent_dir")

    def test_all_7_knowledge_base_pdfs_exist(self):
        for pdf_name in EXPECTED_PDF_FILES:
            pdf_path = KNOWLEDGE_BASE_DIR / pdf_name
            assert pdf_path.is_file(), f"Missing required policy document: {pdf_name}"

    def test_parse_directory_extracts_all_7_pdfs(self):
        chunks = self.parser.parse_directory(KNOWLEDGE_BASE_DIR, target_words=120, overlap_words=30)

        # 7 documents parsed into 12 total chunks
        assert len(chunks) == 12
        parsed_docs = {chunk.document_name for chunk in chunks}
        assert parsed_docs == set(EXPECTED_PDF_FILES)

    def test_provenance_metadata_and_invariants(self):
        chunks = self.parser.parse_directory(KNOWLEDGE_BASE_DIR, target_words=120, overlap_words=30)

        for chunk in chunks:
            assert isinstance(chunk, DocumentChunk)
            assert chunk.chunk_id.startswith(chunk.metadata["document_stem"])
            assert chunk.document_name in EXPECTED_PDF_FILES
            assert len(chunk.chunk_content) > 0
            assert chunk.word_count == len(chunk.chunk_content.split())
            assert chunk.char_length == len(chunk.chunk_content)
            assert chunk.word_count <= 120
            assert chunk.section_title is not None

            # Provenance metadata checks
            meta = chunk.metadata
            assert meta["source_file"] == chunk.document_name
            assert meta["source_path"].endswith(chunk.document_name)
            assert "chunk_index" in meta
            assert "total_chunks" in meta
            assert meta["target_words"] == 120
            assert meta["overlap_words"] == 30
            assert meta["start_word_index"] >= 0
            assert meta["end_word_index"] >= meta["start_word_index"]

    def test_multi_chunk_boundary_overlap_on_real_policy_pdfs(self):
        # refund_policy.pdf has 177 words -> 2 chunks (120 words, 89 words with 30-word overlap)
        refund_chunks = self.parser.parse_document(
            KNOWLEDGE_BASE_DIR / "refund_policy.pdf",
            target_words=120,
            overlap_words=30,
        )
        assert len(refund_chunks) == 2

        c0_words = refund_chunks[0].chunk_content.split()
        c1_words = refund_chunks[1].chunk_content.split()

        assert len(c0_words) == 120
        assert len(c1_words) == 89  # 177 - 90 + 2 (from cleaning/bullet additions)

        # Verify 30-word overlap
        overlap_c0 = c0_words[-30:]
        overlap_c1 = c1_words[:30]
        assert overlap_c0 == overlap_c1

    def test_parse_all_policies_returns_complete_dictionary(self):
        policy_dict = self.parser.parse_all_policies(KNOWLEDGE_BASE_DIR)

        assert len(policy_dict) == 7
        for doc_name in EXPECTED_PDF_FILES:
            assert doc_name in policy_dict
            doc_chunks = policy_dict[doc_name]
            assert len(doc_chunks) >= 1
            for c in doc_chunks:
                assert c.document_name == doc_name
