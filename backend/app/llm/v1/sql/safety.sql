-- Apply explicitly using an owner/migration connection. Runtime needs SELECT only.
CREATE SCHEMA IF NOT EXISTS llm_v1;
CREATE TABLE IF NOT EXISTS llm_v1.safety_snapshot (
    run_id text PRIMARY KEY REFERENCES product_search.ingestion_runs(run_id),
    rules_complete boolean NOT NULL DEFAULT false,
    source text NOT NULL,
    code_system text NOT NULL CHECK (code_system = 'DUR'),
    imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS llm_v1.product_ingredients (
    run_id text NOT NULL REFERENCES llm_v1.safety_snapshot(run_id),
    product_key text NOT NULL,
    codes text[] NOT NULL CHECK (cardinality(codes) > 0),
    complete boolean NOT NULL DEFAULT false,
    source text NOT NULL,
    PRIMARY KEY(run_id, product_key)
);
CREATE TABLE IF NOT EXISTS llm_v1.contraindication (
    run_id text NOT NULL REFERENCES llm_v1.safety_snapshot(run_id),
    rule_id text NOT NULL,
    left_codes text[] NOT NULL CHECK (cardinality(left_codes) > 0),
    right_codes text[] NOT NULL CHECK (cardinality(right_codes) > 0),
    content text NOT NULL,
    conditions text NOT NULL DEFAULT '',
    source text NOT NULL,
    PRIMARY KEY(run_id, rule_id)
);
CREATE INDEX IF NOT EXISTS contraindication_left_idx ON llm_v1.contraindication USING gin(left_codes);
CREATE INDEX IF NOT EXISTS contraindication_right_idx ON llm_v1.contraindication USING gin(right_codes);
