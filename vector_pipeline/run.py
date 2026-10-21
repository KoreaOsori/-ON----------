import argparse
import json
import os

from bundle import prepare, validate_bundle
from config import settings


def main():
    parser = argparse.ArgumentParser(description="Silver → deduplicated documents → durable embeddings → pgvector")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="로컬/S3 Parquet → v2 bundle, DB/임베딩 호출 없음")
    prep.add_argument("--drug", required=True)
    prep.add_argument("--health-food", required=True)
    prep.add_argument("--output", required=True)
    prep.add_argument("--max-chars", type=int, default=1800)
    prep.add_argument("--min-chars", type=int, default=900)
    prep.add_argument("--overlap", type=int, default=150)
    prep.add_argument("--limit", type=int, default=0)
    silver = sub.add_parser("prepare-silver", help="두 제품이 모두 있는 최신 날짜 → prepare")
    silver.add_argument("--bucket", default=settings()["silver"]["bucket"])
    silver.add_argument("--prefix", default=settings()["silver"]["prefix"])
    silver.add_argument("--snapshot", help="특정 공통 날짜 지정 (YYYY-MM-DD)")
    silver.add_argument("--output", required=True)
    silver.add_argument("--max-chars", type=int, default=1800)
    silver.add_argument("--min-chars", type=int, default=900)
    silver.add_argument("--overlap", type=int, default=150)
    silver.add_argument("--limit", type=int, default=0)
    sync = sub.add_parser("sync-silver", help="최신 공통 날짜 prepare → embed → ingest → 공개")
    sync.add_argument("--output", default="output/sync")
    sync.add_argument("--cache", default="output/embedding-cache.sqlite")
    sync.add_argument("--workers", type=int, default=4)
    sync.add_argument("--batch-size", type=int, default=128)
    sync.add_argument("--retry-failed", action="store_true")
    check = sub.add_parser("validate")
    check.add_argument("--input", required=True)
    sub.add_parser("init-db", help="RDS 준비 후 명시적 초기화. v1 DB 자동 변경 없음")
    sub.add_parser("check-db", help="읽기 전용 DB 연결 검사; 테이블 생성 없음")
    sub.add_parser("create-index", help="대량 적재 후 명시적으로 HNSW 생성")
    rollback = sub.add_parser("rollback", help="보존된 완료 run으로 명시적 롤백, 이력 기록")
    rollback.add_argument("--run-id", required=True)
    rollback.add_argument("--reason", required=True)
    prune = sub.add_parser("prune", help="오래된 run/고아 벡터 정리. 기본 dry-run")
    prune.add_argument("--keep-last", type=int, default=2)
    prune.add_argument("--older-than-days", type=int, default=30)
    prune.add_argument("--include-incomplete", action="store_true")
    prune.add_argument("--apply", action="store_true")
    prune.add_argument("--batch-size", type=int, default=1000)
    search = sub.add_parser("search", help="제품명 조회 → 해당 제품의 관련 청크 exact 검색")
    search.add_argument("--query")
    search.add_argument("--product-name")
    search.add_argument("--product-key", action="append", dest="product_keys")
    search.add_argument("--product-type", choices=("drug", "health_food"))
    search.add_argument("--section-type")
    search.add_argument("--top-k", type=int, default=10)
    for name in ("embed", "ingest"):
        command = sub.add_parser(name, help="Bedrock 임베딩·캐시" if name == "embed" else "캐시 → RDS 배치 적재, 임베딩 호출 없음")
        command.add_argument("--input", required=True)
        command.add_argument("--cache", default="output/embedding-cache.sqlite")
        command.add_argument("--batch-size", type=int, default=128)
        if name == "embed":
            command.add_argument("--workers", type=int, default=4)
            command.add_argument("--retry-failed", action="store_true", help="기록된 실패도 다시 시도")
        else:
            command.add_argument("--publish", action="store_true", help="전체 bundle 검증 후 활성 스냅샷 전환")
    args = parser.parse_args()
    if args.command == "sync-silver":
        from sync_silver import sync_silver
        result = sync_silver(args)
    elif args.command == "prepare-silver":
        from aws_runtime import silver_sources
        sources = silver_sources(args.bucket, args.prefix, args.snapshot)
        args.drug, args.health_food = sources["drug_product"], sources["health_food_product"]
        args.expected_snapshot = args.drug.split("/")[-2].removeprefix("snapshot=")
        result = prepare(args)
    elif args.command == "prepare":
        result = prepare(args)
    elif args.command == "check-db":
        from vector_store import connect
        with connect() as conn:
            row = conn.execute("SELECT current_database(), current_user").fetchone()
        result = {"connected": True, "database": row[0], "user": row[1]}
    elif args.command == "validate":
        _, result = validate_bundle(args.input)
    else:
        from config import EmbeddingConfig
        config = EmbeddingConfig.from_env()
        if args.command in ("init-db", "create-index"):
            from vector_store import create_index, init_db
            (init_db if args.command == "init-db" else create_index)(config)
            result = {"command": args.command, "embedding_version": config.version}
        elif args.command == "rollback":
            from lifecycle import rollback
            result = rollback(config, args.run_id, args.reason)
        elif args.command == "prune":
            from lifecycle import prune
            result = prune(config, args.keep_last, args.older_than_days, args.apply, args.include_incomplete, args.batch_size)
        elif args.command == "search":
            from search import retrieve
            from embedding import BedrockEmbedder
            result = retrieve(config, args.query, args.product_name, args.product_keys, args.product_type,
                              args.section_type, args.top_k, BedrockEmbedder(config) if args.query else None)
        else:
            if not 1 <= args.batch_size <= 1000:
                parser.error("batch-size는 1~1000이어야 합니다.")
            root, manifest = validate_bundle(args.input)
            if args.command == "embed":
                if not 1 <= args.workers <= 32:
                    parser.error("workers는 1~32이어야 합니다.")
                from embed_pipeline import embed_bundle
                from embedding import BedrockEmbedder
                result = embed_bundle(root, manifest, config, BedrockEmbedder(config), args.cache, args.workers, args.batch_size, args.retry_failed)
            else:
                from vector_store import ingest
                result = ingest(root, manifest, config, args.cache, args.batch_size, args.publish)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.command in ("embed", "sync-silver") and not result.get("complete", True):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
