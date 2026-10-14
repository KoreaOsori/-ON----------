"""CLI retrieval contract: product-name lookup -> scoped, exact vector ranking."""
import json

from embedding import validate_vector
from vector_store import check_config, connect


def like_literal(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_products(conn, run_id, name, product_type=None, limit=20):
    name = name.strip().lower()
    if not name or not 1 <= limit <= 100:
        raise ValueError("제품명과 1~100 사이 limit이 필요합니다.")
    predicate = "run_id=%s AND section_type='overview'"
    common = [run_id]
    if product_type:
        predicate += " AND product_type=%s"
        common.append(product_type)
    for mode, condition, value in (
        ("exact", "lower(product_name)=%s", name),
        ("prefix", "lower(product_name) LIKE %s", like_literal(name) + "%"),
        ("contains", "lower(product_name) LIKE %s", "%" + like_literal(name) + "%"),
    ):
        # Very short substring searches cannot use trigrams efficiently; prefix remains available.
        if mode == "contains" and len(name) < 3:
            continue
        rows = conn.execute("SELECT DISTINCT product_key,product_name,manufacturer,product_type FROM product_search.product_links "
                            f"WHERE {predicate} AND {condition} ORDER BY product_key LIMIT %s",
                            (*common, value, limit + 1)).fetchall()
        if rows:
            return {"mode": mode, "truncated": len(rows) > limit,
                    "products": [dict(zip(("product_key", "product_name", "manufacturer", "product_type"), r)) for r in rows[:limit]]}
    return {"mode": "not_found", "truncated": False, "products": []}


def filter_clause(run_id, product_keys=None, product_type=None, section_type=None):
    clauses, params = ["l.run_id=%s"], [run_id]
    if product_keys is not None:
        clauses.append("l.product_key=ANY(%s)")
        params.append(product_keys)
    if product_type:
        clauses.append("l.product_type=%s")
        params.append(product_type)
    if section_type:
        clauses.append("l.section_type=%s")
        params.append(section_type)
    return " AND ".join(clauses), params


def rank_exact(conn, run_id, vector, top_k=10, product_keys=None, product_type=None, section_type=None):
    if not 1 <= top_k <= 100:
        raise ValueError("top-k는 1~100이어야 합니다.")
    where, params = filter_clause(run_id, product_keys, product_type, section_type)
    # Materialization creates the complete filtered candidate set BEFORE distance ordering.
    # No ANN post-filtering and no short-result fallback guess; potentially slower globally.
    sql = ("WITH candidates AS MATERIALIZED (SELECT v.content_hash,v.embedding FROM product_search.product_vectors v "
           f"WHERE EXISTS(SELECT 1 FROM product_search.product_links l WHERE l.content_hash=v.content_hash AND {where})), "
           "ranked AS (SELECT content_hash,embedding <=> %s::vector AS distance FROM candidates "
           "ORDER BY distance,content_hash LIMIT %s) "
           "SELECT v.content_hash,v.content,v.product_type,v.section_type,r.distance FROM ranked r "
           "JOIN product_search.product_vectors v USING(content_hash) ORDER BY r.distance,v.content_hash")
    rows = conn.execute(sql, (*params, json.dumps(vector), top_k)).fetchall()
    results = []
    for h, content, kind, section, distance in rows:
        refs = conn.execute("SELECT l.product_key,l.product_name,l.manufacturer,l.source_refs,l.metadata,l.source_s3_key,l.snapshot,l.sale_status, "
                            "count(*) OVER() FROM product_search.product_links l "
                            f"WHERE l.content_hash=%s AND {where} ORDER BY l.product_key,l.chunk_index LIMIT 50", (h, *params)).fetchall()
        results.append({"content_hash": h, "content": content, "product_type": kind, "section_type": section,
                        "distance": distance, "source_count": refs[0][-1] if refs else 0,
                        "sources": [dict(zip(("product_key", "product_name", "manufacturer", "source_refs", "metadata", "source_s3_key", "snapshot", "sale_status"), r[:-1])) for r in refs]})
    return results


def retrieve(config, query=None, product_name=None, product_keys=None, product_type=None, section_type=None, top_k=10, embedder=None):
    if not query and not product_name:
        raise ValueError("query 또는 product-name이 필요합니다.")
    if product_type not in (None, "drug", "health_food") or not 1 <= top_k <= 100:
        raise ValueError("잘못된 검색 필터 또는 top-k")
    with connect() as conn:
        check_config(conn, config)
        with conn.transaction():
            # A publish/prune between queries must not mix two snapshots.
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            active = conn.execute("SELECT run_id FROM product_search.active_snapshot WHERE singleton").fetchone()
            if not active:
                raise ValueError("공개된 스냅샷이 없습니다.")
            run_id = active[0]
            resolved = find_products(conn, run_id, product_name, product_type) if product_name else None
            if resolved is not None:
                if resolved["truncated"]:
                    raise ValueError("제품 후보가 너무 많습니다. 이름을 구체화하거나 product-key를 지정하세요.")
                names = [p["product_key"] for p in resolved["products"]]
                product_keys = [k for k in names if k in product_keys] if product_keys is not None else names
                if not product_keys or not query:
                    return {"run_id": run_id, "resolved": resolved, "results": []}
            if embedder is None:
                raise ValueError("질문 검색에는 임베딩 어댑터가 필요합니다.")
            vector = embedder.embed(query)
            validate_vector(vector, config.dimensions)
            return {"run_id": run_id, "resolved": resolved, "mode": "exact",
                    "results": rank_exact(conn, run_id, vector, top_k, product_keys, product_type, section_type)}
