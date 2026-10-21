import json

from sqlalchemy import text

from .config import Settings


class DataUnavailable(Exception):
    pass


class Repository:
    """One repeatable-read transaction per question, pinned to one published run."""

    def __init__(self, connection, settings: Settings):
        self.conn = connection
        self.settings = settings
        self.run_id = None

    async def rows(self, sql, **params):
        result = await self.conn.execute(text(sql), params)
        return [dict(row) for row in result.mappings()]

    async def start(self):
        config = await self.rows("SELECT * FROM product_search.pipeline_config WHERE singleton")
        if not config or (config[0]["schema_version"], config[0]["embedding_version"], config[0]["dimensions"]) != (
                2, self.settings.embedding_version, self.settings.embedding_dimensions):
            raise DataUnavailable("벡터 DB 임베딩 모델·차원·스키마 설정을 확인하세요.")
        runs = await self.rows("SELECT run_id FROM product_search.active_snapshot WHERE singleton")
        if not runs:
            raise DataUnavailable("공개된 제품 데이터가 없습니다.")
        self.run_id = runs[0]["run_id"]

    async def resolve(self, product):
        base = """SELECT DISTINCT product_key,product_name,manufacturer,product_type
                  FROM product_search.product_links WHERE run_id=:run AND section_type='overview'
                  AND (CAST(:kind AS text) IS NULL OR product_type=:kind)"""
        params = {"run": self.run_id, "kind": product.product_type}
        if product.product_key:
            rows = await self.rows(base + " AND product_key=:key", **params, key=product.product_key)
            return rows, bool(rows)
        rows = await self.rows(base + " AND lower(product_name)=lower(:name) ORDER BY product_key LIMIT 11",
                               **params, name=product.name)
        if rows:
            return rows[:10], len(rows) == 1
        # Literal substring; do not treat user input as SQL LIKE wildcards.
        escaped = product.name.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = await self.rows(base + """ AND (lower(product_name) LIKE :pattern
                   OR similarity(lower(product_name),lower(:name)) >= 0.2)
                   ORDER BY product_key LIMIT 10""", **params, pattern=f"%{escaped}%", name=product.name)
        return rows, False

    async def documents(self, key, section, vector=None):
        # Benefits are ranked within the confirmed product. Precautions are fetched in full.
        order = "distance, l.chunk_index" if vector is not None else "l.chunk_index"
        distance = "v.embedding <=> CAST(:vector AS vector)" if vector is not None else "0.0"
        limit = self.settings.top_k if vector is not None else 101
        rows = await self.rows(f"""SELECT l.chunk_id,l.product_key,l.section_type,l.source_refs,
            l.source_s3_key,l.snapshot,v.content, {distance} AS distance
            FROM product_search.product_links l JOIN product_search.product_vectors v USING(content_hash)
            WHERE l.run_id=:run AND l.product_key=:key AND l.section_type=:section
            ORDER BY {order} LIMIT :limit""", run=self.run_id, key=key, section=section,
            vector=json.dumps(vector), limit=limit)
        if vector is not None:
            rows = [r for r in rows if r["distance"] <= self.settings.max_distance]
        elif len(rows) > 100:
            raise DataUnavailable("주의사항이 너무 많습니다. 제품 수를 줄이거나 원문을 확인하세요.")
        return rows

    async def safety(self, keys):
        exists = await self.rows("SELECT to_regclass('llm_v1.safety_snapshot') AS name")
        if not exists[0]["name"]:
            return {}, [], False
        snapshot = await self.rows("SELECT rules_complete FROM llm_v1.safety_snapshot WHERE run_id=:run",
                                   run=self.run_id)
        if not snapshot:
            return {}, [], False
        products = await self.rows("""SELECT product_key,codes,complete,source FROM llm_v1.product_ingredients
            WHERE run_id=:run AND product_key=ANY(CAST(:keys AS text[]))""", run=self.run_id, keys=keys)
        codes = sorted({c for p in products for c in p["codes"]})
        rules = await self.rows("""SELECT rule_id,left_codes,right_codes,content,conditions,source
            FROM llm_v1.contraindication WHERE run_id=:run
            AND left_codes && CAST(:codes AS text[]) AND right_codes && CAST(:codes AS text[])""",
            run=self.run_id, codes=codes)
        return {p["product_key"]: p for p in products}, rules, snapshot[0]["rules_complete"]
