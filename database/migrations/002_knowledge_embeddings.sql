-- =============================================================================
-- Migration: 002_knowledge_embeddings.sql
-- Description: Knowledge Embeddings Table, HNSW Vector Index & Full-Text Search
-- Step: Step 5 — Phase 2: Vector Embeddings & Database Persistence
-- Author: ResolveX Engineering
-- =============================================================================

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create knowledge_embeddings table
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    id BIGSERIAL PRIMARY KEY,
    chunk_id VARCHAR(64) NOT NULL UNIQUE,
    document_name VARCHAR(255) NOT NULL,
    section_title VARCHAR(255),
    chunk_content TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv_content tsvector GENERATED ALWAYS AS (to_tsvector('english', chunk_content)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Trigger for updated_at column
DROP TRIGGER IF EXISTS update_knowledge_embeddings_updated_at ON knowledge_embeddings;
CREATE TRIGGER update_knowledge_embeddings_updated_at
    BEFORE UPDATE ON knowledge_embeddings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 4. HNSW Index for Dense Cosine Similarity Search
-- Pareto frontier parameters: m = 16, ef_construction = 64
CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_hnsw 
ON knowledge_embeddings 
USING hnsw (embedding vector_cosine_ops) 
WITH (m = 16, ef_construction = 64);

-- 5. GIN Index for Full-Text Search (Sparse Keyword Search)
CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_tsv 
ON knowledge_embeddings 
USING gin(tsv_content);

-- 6. B-Tree Indexes for fast document filtering
CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_chunk_id ON knowledge_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_doc_name ON knowledge_embeddings(document_name);

-- 7. Grant Permissions to standard Supabase API roles
GRANT ALL ON TABLE knowledge_embeddings TO anon, authenticated, service_role;
GRANT ALL ON SEQUENCE knowledge_embeddings_id_seq TO anon, authenticated, service_role;

-- 8. Row Level Security (RLS)
ALTER TABLE knowledge_embeddings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow read access to knowledge_embeddings" ON knowledge_embeddings;
CREATE POLICY "Allow read access to knowledge_embeddings" ON knowledge_embeddings
    FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS "Allow write access to knowledge_embeddings" ON knowledge_embeddings;
CREATE POLICY "Allow write access to knowledge_embeddings" ON knowledge_embeddings
    FOR ALL TO anon, authenticated, service_role USING (true) WITH CHECK (true);
