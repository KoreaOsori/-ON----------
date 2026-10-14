-- Explicit post-load step. Autocommit required by CONCURRENTLY.
CREATE INDEX CONCURRENTLY IF NOT EXISTS product_vectors_embedding_idx
    ON product_search.product_vectors USING hnsw (embedding vector_cosine_ops);
