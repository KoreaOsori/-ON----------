-- v2: normalized unique vectors and versioned product links. No HNSW during load.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE SCHEMA IF NOT EXISTS product_search;
CREATE TABLE IF NOT EXISTS product_search.pipeline_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    schema_version integer NOT NULL,
    embedding_version text NOT NULL,
    dimensions integer NOT NULL
);
CREATE TABLE IF NOT EXISTS product_search.product_vectors (
    content_hash text PRIMARY KEY,
    product_type text NOT NULL CHECK(product_type IN ('drug','health_food')),
    section_type text NOT NULL,
    content text NOT NULL,
    embedding vector(__DIMENSIONS__) NOT NULL
);
CREATE TABLE IF NOT EXISTS product_search.ingestion_runs (
    run_id text PRIMARY KEY,
    snapshot date NOT NULL,
    manifest jsonb NOT NULL,
    status text NOT NULL CHECK(status IN ('loading','complete','pruning')),
    documents_loaded bigint NOT NULL DEFAULT 0,
    links_loaded bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Additive v2 update; init-db may be rerun after upgrading this folder.
ALTER TABLE product_search.ingestion_runs DROP CONSTRAINT IF EXISTS ingestion_runs_status_check;
ALTER TABLE product_search.ingestion_runs ADD CONSTRAINT ingestion_runs_status_check CHECK(status IN ('loading','complete','pruning'));
CREATE TABLE IF NOT EXISTS product_search.product_links (
    run_id text NOT NULL REFERENCES product_search.ingestion_runs(run_id),
    chunk_id text NOT NULL,
    content_hash text NOT NULL REFERENCES product_search.product_vectors(content_hash),
    product_type text NOT NULL,
    source_product_id text NOT NULL,
    product_key text NOT NULL,
    product_name text NOT NULL,
    manufacturer text NOT NULL,
    section_type text NOT NULL,
    source_refs jsonb NOT NULL,
    metadata jsonb NOT NULL,
    chunk_index integer NOT NULL,
    document_version text NOT NULL,
    source_s3_key text NOT NULL,
    snapshot date NOT NULL,
    sale_status text,
    PRIMARY KEY(run_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS product_links_hash_idx ON product_search.product_links(run_id,content_hash);
CREATE INDEX IF NOT EXISTS product_links_product_idx ON product_search.product_links(run_id,product_key,section_type);
CREATE INDEX IF NOT EXISTS product_links_content_idx ON product_search.product_links(content_hash);
CREATE INDEX IF NOT EXISTS product_links_name_prefix_idx
    ON product_search.product_links(run_id,lower(product_name) text_pattern_ops) WHERE section_type='overview';
CREATE INDEX IF NOT EXISTS product_links_name_trgm_idx
    ON product_search.product_links USING gin(lower(product_name) gin_trgm_ops) WHERE section_type='overview';
CREATE TABLE IF NOT EXISTS product_search.active_snapshot (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    run_id text NOT NULL REFERENCES product_search.ingestion_runs(run_id)
);
CREATE OR REPLACE VIEW product_search.active_product_links AS
    SELECT l.* FROM product_search.product_links l
    JOIN product_search.active_snapshot a USING(run_id);
CREATE OR REPLACE VIEW product_search.active_vectors AS
    SELECT v.* FROM product_search.product_vectors v
    WHERE EXISTS (SELECT 1 FROM product_search.active_product_links l WHERE l.content_hash=v.content_hash);
CREATE TABLE IF NOT EXISTS product_search.publication_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_run_id text,
    to_run_id text NOT NULL,
    operation text NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
