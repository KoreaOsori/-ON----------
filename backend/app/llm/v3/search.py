"""벡터 검색 (강의의 retrieval.py 에 해당).

vector_pipeline/search.py 의 find_products / rank_exact 를 asyncpg(SQLAlchemy text) 스타일로 옮긴 것이다.
- 제품명 식별(exact → prefix → contains) → 해당 제품 범위의 exact 코사인 순위.
- 벡터는 "[0.1,0.2,...]" 문자열로 넘기고 SQL 에서 CAST(:q AS vector) 로 변환한다 → pgvector 파이썬 패키지 불필요.
- SQL 은 전부 이름 있는 파라미터로 바인딩한다. 사용자/LLM 입력을 SQL 문자열에 이어 붙이지 않는다.
  (f-string 으로 들어가는 것은 이 파일 안의 고정 조각(where 절)뿐이다.)
- 가짜 Reader 로 DB 없이 테스트할 수 있다.
"""
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from app.llm.v3.config import SCHEMA_VERSION, V3Settings
from app.llm.v3.db import Reader
from app.llm.v3.names import collapse_spaces, fold_brackets, name_variants, narrow_by_manufacturer

SCHEMA = "product_search"
PRODUCT_TYPES = ("drug", "health_food")
SECTION_TYPES = ("overview", "ingredients", "benefits", "usage", "precautions", "interactions", "storage", "additional")
MAX_CANDIDATE_PRODUCTS = 20
# 주의사항 중 '복용하면 안 되는 경우(금기)' 문단의 표지. 벡터 거리로는 '먹으면 안 되는 사람' 같은 질문과 멀 수 있어 따로 찾는다.
CONTRAINDICATION_PATTERNS = (
    "%투여하지 말%", "%복용하지 말%", "%사용하지 말%", "%투여하지 마%", "%복용하지 마%", "%투여하지 않%",
)
PRODUCT_KEY_PATTERN = re.compile(r"^(drug|health_food):[\w.\-]{1,100}$")


class SearchConfigError(RuntimeError):
    """DB 의 스키마/임베딩 설정이 이 코드와 맞지 않는다. 자동으로 고치지 않고 중단한다."""


def like_literal(text: str) -> str:
    """LIKE 패턴의 특수문자(\\ % _)를 문자 그대로 매칭하도록 이스케이프."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def check_config(reader: Reader, settings: V3Settings) -> None:
    """pipeline_config 가 (schema 2, 같은 임베딩 버전, 같은 차원)인지 확인. 다른 임베딩 공간이면 검색하지 않는다."""
    rows = await reader.fetch(
        f"SELECT schema_version, embedding_version, dimensions FROM {SCHEMA}.pipeline_config WHERE singleton"
    )
    found = (rows[0]["schema_version"], rows[0]["embedding_version"], rows[0]["dimensions"]) if rows else None
    if found != (SCHEMA_VERSION, settings.embedding_version, settings.embedding_dimensions):
        raise SearchConfigError("DB 스키마 또는 임베딩 모델/차원이 일치하지 않습니다.")


async def active_run_id(reader: Reader) -> str | None:
    rows = await reader.fetch(f"SELECT run_id FROM {SCHEMA}.active_snapshot WHERE singleton")
    return rows[0]["run_id"] if rows else None


_PRODUCT_COLUMNS = ("product_key", "product_name", "manufacturer", "product_type")


def _product_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: r[k] for k in _PRODUCT_COLUMNS} for r in rows]


async def find_products(
    reader: Reader, run_id: str, name: str, product_type: str | None = None, limit: int = MAX_CANDIDATE_PRODUCTS
) -> dict[str, Any]:
    """제품명으로 후보 조회.

    단계(exact → prefix → contains(3자 이상))를 바깥 루프로, 입력 변형(names.name_variants)을 안쪽 루프로 돈다.
    → 원래 입력이 어느 단계에서든 먼저 맞으면 괄호를 뗀 변형보다 우선한다.
    approximate=True 면 사용자가 말한 괄호 내용을 버린 변형으로 찾은 것이다.
    """
    variants = name_variants(name)
    if not variants or not 1 <= limit <= 100:
        raise ValueError("제품명과 1~100 사이 limit이 필요합니다.")
    if product_type not in (None, *PRODUCT_TYPES):
        raise ValueError("잘못된 product_type")

    predicate = "run_id = :run_id AND section_type = 'overview'"
    base: dict[str, Any] = {"run_id": run_id, "limit": limit + 1}
    if product_type:
        predicate += " AND product_type = :product_type"
        base["product_type"] = product_type

    for mode, condition in (
        ("exact", "lower(product_name) = :value"),
        ("prefix", "lower(product_name) LIKE :value"),
        ("contains", "lower(product_name) LIKE :value"),
    ):
        for text, approximate in variants:
            # 아주 짧은 부분 문자열은 트라이그램 인덱스를 못 쓴다. 접두어 검색만 허용.
            if mode == "contains" and len(text) < 3:
                continue
            value = {"exact": text, "prefix": like_literal(text) + "%", "contains": "%" + like_literal(text) + "%"}[mode]
            rows = await reader.fetch(
                f"SELECT DISTINCT product_key, product_name, manufacturer, product_type FROM {SCHEMA}.product_links "
                f"WHERE {predicate} AND {condition} ORDER BY product_key LIMIT :limit",
                {**base, "value": value},
            )
            if rows:
                found = _product_rows(rows[:limit])
                truncated = len(rows) > limit
                if not truncated:  # 제조사까지 적었으면 같은 이름의 제품 중 그 제조사 것만 남긴다(일치하면 정확한 지정으로 본다)
                    narrowed = narrow_by_manufacturer(name, found)
                    if len(narrowed) < len(found):
                        found, approximate = narrowed, False
                return {
                    "mode": mode,
                    "approximate": approximate,
                    "matched_as": text,
                    "truncated": truncated,
                    "products": found,
                }
    brand = await _find_by_brand(reader, name, predicate, base, limit)
    if brand is not None:
        return brand
    return {"mode": "not_found", "approximate": False, "matched_as": None, "truncated": False, "products": []}


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
MAX_BRAND_ROWS = 100


async def _find_by_brand(
    reader: Reader, name: str, predicate: str, base: dict[str, Any], limit: int
) -> dict[str, Any] | None:
    """띄어 쓴 이름("타이레놀 500mg")을 전체로 못 찾았을 때: 첫 단어(브랜드)로 시작하는 제품을 찾고, 나머지에 숫자(함량)가 있으면
    그 숫자가 이름에 들어 있는 제품으로 좁힌다. 근사 일치(approximate)로 표시하며, 여럿이면 호출 쪽이 되묻는다."""
    tokens = collapse_spaces(fold_brackets(name)).split(" ")
    if len(tokens) < 2 or len(tokens[0]) < 2:
        return None
    brand = tokens[0].lower()
    rows = await reader.fetch(
        f"SELECT DISTINCT product_key, product_name, manufacturer, product_type FROM {SCHEMA}.product_links "
        f"WHERE {predicate} AND lower(product_name) LIKE :value ORDER BY product_key LIMIT :limit",
        {**base, "value": like_literal(brand) + "%", "limit": MAX_BRAND_ROWS + 1},
    )
    if not rows:
        return None
    found = _product_rows(rows[:MAX_BRAND_ROWS])
    numbers = _NUMBER.findall(" ".join(tokens[1:]))
    if numbers:
        narrowed = [p for p in found if all(n in p["product_name"] for n in numbers)]
        if narrowed:
            found = narrowed
    return {
        "mode": "brand",
        "approximate": True,
        "matched_as": brand,
        "truncated": len(found) > limit or len(rows) > MAX_BRAND_ROWS and not numbers,
        "products": found[:limit],
    }


async def find_by_key(reader: Reader, run_id: str, product_key: str) -> dict[str, Any] | None:
    """product_key 로 제품 하나를 확인(사용자가 후보 중에서 고른 경우)."""
    if not PRODUCT_KEY_PATTERN.match(product_key):
        raise ValueError("잘못된 product_key")
    rows = await reader.fetch(
        f"SELECT DISTINCT product_key, product_name, manufacturer, product_type FROM {SCHEMA}.product_links "
        "WHERE run_id = :run_id AND section_type = 'overview' AND product_key = :product_key",
        {"run_id": run_id, "product_key": product_key},
    )
    return _product_rows(rows[:1])[0] if rows else None


MAX_SECTION_CHUNKS = 100


async def fetch_section_texts(
    reader: Reader, run_id: str, product_key: str, section_type: str, limit: int = MAX_SECTION_CHUNKS
) -> dict[str, Any]:
    """제품 하나의 한 섹션 문단을 순서대로 전부 가져온다(임베딩·순위 없음).

    건강기능식품 섭취 주의사항처럼 일부만 보여 주면 안 되는 내용에 쓴다. 같은 본문(content_hash)은 한 번만 담는다.
    limit 을 넘으면 truncated=True 로 알리고 limit 개까지만 돌려준다.
    """
    if not PRODUCT_KEY_PATTERN.match(product_key):
        raise ValueError("잘못된 product_key")
    if section_type not in SECTION_TYPES:
        raise ValueError("잘못된 section_type")
    if not 1 <= limit <= 200:
        raise ValueError("limit은 1~200이어야 합니다.")
    rows = await reader.fetch(
        "SELECT l.chunk_index, v.content_hash, v.content "
        f"FROM {SCHEMA}.product_links l JOIN {SCHEMA}.product_vectors v USING (content_hash) "
        "WHERE l.run_id = :run_id AND l.product_key = :product_key AND l.section_type = :section_type "
        "ORDER BY l.chunk_index, v.content_hash LIMIT :limit",
        {"run_id": run_id, "product_key": product_key, "section_type": section_type, "limit": limit + 1},
    )
    seen: set[str] = set()
    chunks: list[str] = []
    for row in rows[:limit]:
        text = (row["content"] or "").strip()
        if text and row["content_hash"] not in seen:
            seen.add(row["content_hash"])
            chunks.append(text)
    return {"chunks": chunks, "truncated": len(rows) > limit}


def filter_clause(
    run_id: str,
    product_keys: list[str] | None = None,
    product_type: str | None = None,
    section_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """product_links(l) 에 거는 필터. 조각은 고정 문자열이고 값은 전부 파라미터."""
    clauses, params = ["l.run_id = :run_id"], {"run_id": run_id}
    if product_keys is not None:
        clauses.append("l.product_key = ANY(CAST(:product_keys AS text[]))")
        params["product_keys"] = list(product_keys)
    if product_type:
        clauses.append("l.product_type = :product_type")
        params["product_type"] = product_type
    if section_type:
        clauses.append("l.section_type = :section_type")
        params["section_type"] = section_type
    return " AND ".join(clauses), params


@dataclass(frozen=True)
class SearchHit:
    content_hash: str
    content: str
    product_type: str
    section_type: str
    distance: float
    source_count: int
    sources: list[dict[str, Any]] = field(default_factory=list)


def _as_json(value: Any) -> Any:
    """jsonb 는 드라이버 설정에 따라 str 또는 객체로 온다."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


async def rank_exact(
    reader: Reader,
    run_id: str,
    vector_text: str,
    top_k: int = 10,
    product_keys: list[str] | None = None,
    product_type: str | None = None,
    section_type: str | None = None,
    content_patterns: tuple[str, ...] | None = None,
) -> list[SearchHit]:
    """필터로 후보를 먼저 확정(MATERIALIZED)한 뒤 exact 코사인 거리로 순위를 매긴다.

    ANN(HNSW) 후보를 필터링하는 방식이 아니므로 후보 누락이 없다. 대신 제품 범위 없이 쓰면 느릴 수 있다.
    content_patterns(이 모듈의 고정 LIKE 패턴만)를 주면 본문이 그중 하나를 포함하는 문단만 후보로 둔다.
    """
    if not 1 <= top_k <= 100:
        raise ValueError("top-k는 1~100이어야 합니다.")
    where, params = filter_clause(run_id, product_keys, product_type, section_type)
    content_clause = ""
    if content_patterns:
        content_clause = " AND (" + " OR ".join(f"v.content LIKE :cp{i}" for i in range(len(content_patterns))) + ")"
        params = {**params, **{f"cp{i}": pattern for i, pattern in enumerate(content_patterns)}}
    rows = await reader.fetch(
        f"WITH candidates AS MATERIALIZED (SELECT v.content_hash, v.embedding FROM {SCHEMA}.product_vectors v "
        f"WHERE EXISTS (SELECT 1 FROM {SCHEMA}.product_links l WHERE l.content_hash = v.content_hash AND {where}){content_clause}), "
        "ranked AS (SELECT content_hash, embedding <=> CAST(:q AS vector) AS distance FROM candidates "
        "ORDER BY distance, content_hash LIMIT :top_k) "
        "SELECT v.content_hash, v.content, v.product_type, v.section_type, r.distance "
        f"FROM ranked r JOIN {SCHEMA}.product_vectors v USING (content_hash) ORDER BY r.distance, v.content_hash",
        {**params, "q": vector_text, "top_k": top_k},
    )
    hits: list[SearchHit] = []
    for row in rows:
        refs = await reader.fetch(
            "SELECT l.product_key, l.product_name, l.manufacturer, l.source_refs, l.metadata, l.source_s3_key, "
            f"l.snapshot, l.sale_status, count(*) OVER () AS total FROM {SCHEMA}.product_links l "
            f"WHERE l.content_hash = :content_hash AND {where} ORDER BY l.product_key, l.chunk_index LIMIT 50",
            {**params, "content_hash": row["content_hash"]},
        )
        sources = [
            {
                **{k: r[k] for k in ("product_key", "product_name", "manufacturer", "source_s3_key", "snapshot", "sale_status")},
                "source_refs": _as_json(r["source_refs"]),
                "metadata": _as_json(r["metadata"]),
            }
            for r in refs
        ]
        hits.append(
            SearchHit(
                content_hash=row["content_hash"],
                content=row["content"],
                product_type=row["product_type"],
                section_type=row["section_type"],
                distance=float(row["distance"]),
                source_count=int(refs[0]["total"]) if refs else 0,
                sources=sources,
            )
        )
    return hits


async def add_contraindication_hits(
    reader: Reader, outcome: "SearchOutcome", vector_text: str, top_k: int = 2
) -> "SearchOutcome":
    """제품 하나로 확정된 검색 결과에 그 제품 주의사항의 금기 문단(CONTRAINDICATION_PATTERNS)을 질문과 가까운 순으로 top_k 개 더한다.

    거리 임계값은 적용하지 않는다(금기 문단은 질문 표현과 멀어도 빠지면 안 된다). 이미 있는 문단은 다시 넣지 않는다."""
    if outcome.status != "ok" or len(outcome.products) != 1 or outcome.run_id is None:
        return outcome
    extra = await rank_exact(
        reader, outcome.run_id, vector_text, top_k, [outcome.products[0]["product_key"]], None, "precautions",
        content_patterns=CONTRAINDICATION_PATTERNS,
    )
    seen = {h.content_hash for h in outcome.hits}
    added = [h for h in extra if h.content_hash not in seen]
    if not added:
        return outcome
    return replace(outcome, hits=[*outcome.hits, *added])


@dataclass(frozen=True)
class SearchOutcome:
    """retrieve 의 결과. 사용자 입력 때문에 생기는 정상적인 '없음/모호함'은 예외가 아니라 status 로 돌려준다."""

    # ok | no_snapshot | product_not_found | ambiguous_product(후보 20개 초과) | needs_clarification(후보 2~20개)
    # | needs_product_name
    status: str
    run_id: str | None = None
    match_mode: str | None = None
    products: list[dict[str, Any]] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    filtered: int = 0  # 거리 임계값 때문에 버린 근거 수
    approximate: bool = False  # 사용자가 말한 괄호 내용을 버린 이름 변형으로 찾았는가
    matched_as: str | None = None  # 실제로 맞은 검색어


async def retrieve(
    reader: Reader,
    settings: V3Settings,
    vector_text: str,
    product_name: str | None = None,
    product_type: str | None = None,
    section_type: str | None = None,
    top_k: int = 5,
    max_distance: float | None = None,
    product_key: str | None = None,
) -> SearchOutcome:
    """제품 식별 → 제품 범위로 한정 → exact 순위 → (지정 시) 거리 임계값으로 관련 없는 근거 제외.

    제품 식별: product_key 가 있으면 그것으로 확정(사용자가 후보 중에서 고른 경우). 없으면 이름 검색이며,
    후보가 2개 이상이면 임의로 고르지 않고 needs_clarification 으로 후보를 돌려준다.

    max_distance=None 이면 거르지 않는다(임계값 튜닝용 평가에서 사용). 도구는 settings.max_distance 를 넘긴다.

    reader 는 REPEATABLE READ READ ONLY 트랜잭션 안에 있어야 한다(db.reader_factory_for).
    """
    if product_type not in (None, *PRODUCT_TYPES):
        raise ValueError("잘못된 product_type")
    if section_type not in (None, *SECTION_TYPES):
        raise ValueError("잘못된 section_type")
    if not 1 <= top_k <= 100:
        raise ValueError("top-k는 1~100이어야 합니다.")
    if max_distance is not None and not 0 <= max_distance <= 2:
        raise ValueError("max_distance는 0~2이어야 합니다.")

    await check_config(reader, settings)
    run_id = await active_run_id(reader)
    if run_id is None:
        return SearchOutcome(status="no_snapshot")

    product_keys: list[str] | None = None
    resolved: dict[str, Any] | None = None
    if product_key:
        product = await find_by_key(reader, run_id, product_key)
        if product is None:
            return SearchOutcome("product_not_found", run_id, "key")
        resolved = {"mode": "key", "approximate": False, "matched_as": product_key, "products": [product]}
        product_keys = [product["product_key"]]
    elif product_name and product_name.strip():
        resolved = await find_products(reader, run_id, product_name, product_type)
        if resolved["truncated"]:
            return SearchOutcome("ambiguous_product", run_id, resolved["mode"], resolved["products"])
        if not resolved["products"]:
            return SearchOutcome("product_not_found", run_id, resolved["mode"])
        if len(resolved["products"]) > 1:
            return SearchOutcome(
                "needs_clarification", run_id, resolved["mode"], resolved["products"],
                approximate=resolved["approximate"], matched_as=resolved["matched_as"],
            )
        product_keys = [p["product_key"] for p in resolved["products"]]
    elif not settings.allow_global_search:
        # 제품 범위 없이 전체 exact 스캔은 하지 않는다(정책). 이름을 먼저 받는다.
        return SearchOutcome("needs_product_name", run_id)

    hits = await rank_exact(reader, run_id, vector_text, top_k, product_keys, product_type, section_type)
    kept = hits if max_distance is None else [h for h in hits if h.distance <= max_distance]
    return SearchOutcome(
        status="ok",
        run_id=run_id,
        match_mode=resolved["mode"] if resolved else "global",
        products=resolved["products"] if resolved else [],
        hits=kept,
        filtered=len(hits) - len(kept),
        approximate=bool(resolved and resolved["approximate"]),
        matched_as=resolved["matched_as"] if resolved else None,
    )
