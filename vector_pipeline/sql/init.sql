-- Run through `python run.py init-db`; __DIMENSIONS__ is validated by config.py.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS product_search;
CREATE TABLE IF NOT EXISTS product_search.index_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    embedding_version text NOT NULL,
    dimensions integer NOT NULL
);
CREATE TABLE IF NOT EXISTS product_search.product_vectors (
    chunk_id text PRIMARY KEY,
    product_type text NOT NULL CHECK (product_type IN ('drug', 'health_food')),
    source_product_id text NOT NULL,
    product_key text NOT NULL,
    section_type text NOT NULL,
    source_ref text NOT NULL,
    chunk_index integer NOT NULL,
    content text NOT NULL,
    content_hash text NOT NULL,
    document_version text NOT NULL,
    source_s3_key text NOT NULL,
    snapshot date NOT NULL,
    sale_status text,
    embedding_version text NOT NULL,
    embedding vector(__DIMENSIONS__) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS product_vectors_product_idx
    ON product_search.product_vectors (product_type, source_product_id, section_type);
CREATE INDEX IF NOT EXISTS product_vectors_hash_idx
    ON product_search.product_vectors (content_hash, embedding_version);
CREATE INDEX IF NOT EXISTS product_vectors_embedding_idx
    ON product_search.product_vectors USING hnsw (embedding vector_cosine_ops);
CREATE TABLE IF NOT EXISTS product_search.ingestion_runs (
    run_id uuid PRIMARY KEY,
    snapshot date NOT NULL,
    chunks bigint NOT NULL,
    manifest jsonb NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now()
);
