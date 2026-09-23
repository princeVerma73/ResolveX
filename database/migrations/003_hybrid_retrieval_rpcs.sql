-- =============================================================================
-- Migration: 003_hybrid_retrieval_rpcs.sql
-- Description: Stored procedures (RPCs) for Dense Vector & Sparse Full-Text Retrieval
-- Step: Step 5 — Phase 3: Hybrid Search (Dense + Sparse Retrieval)
-- Author: ResolveX Engineering
-- =============================================================================

-- 1. Dense Semantic Similarity Search RPC Function
-- Calculates 1 - (embedding <=> query_embedding) as similarity score
-- Leverages HNSW index idx_knowledge_embeddings_hnsw
CREATE OR REPLACE FUNCTION match_knowledge_dense(
    query_embedding vector(768),
    match_count int DEFAULT 20
)
RETURNS TABLE (
    chunk_id varchar,
    document_name varchar,
    section_title varchar,
    chunk_content text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        chunk_id,
        document_name,
        section_title,
        chunk_content,
        (1 - (embedding <=> query_embedding))::float AS similarity
    FROM knowledge_embeddings
    ORDER BY embedding <=> query_embedding ASC
    LIMIT match_count;
$$;

-- 2. Sparse Lexical Full-Text Search RPC Function
-- Utilizes websearch_to_tsquery for safe query parsing and ts_rank_cd for cover density ranking
-- Leverages GIN index idx_knowledge_embeddings_tsv
CREATE OR REPLACE FUNCTION match_knowledge_sparse(
    query_text text,
    match_count int DEFAULT 20
)
RETURNS TABLE (
    chunk_id varchar,
    document_name varchar,
    section_title varchar,
    chunk_content text,
    score float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        chunk_id,
        document_name,
        section_title,
        chunk_content,
        ts_rank_cd(tsv_content, websearch_to_tsquery('english', query_text))::float AS score
    FROM knowledge_embeddings
    WHERE tsv_content @@ websearch_to_tsquery('english', query_text)
    ORDER BY score DESC
    LIMIT match_count;
$$;

-- 3. Grant execute permissions to standard Supabase API roles
GRANT EXECUTE ON FUNCTION match_knowledge_dense(vector(768), int) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION match_knowledge_sparse(text, int) TO anon, authenticated, service_role;
