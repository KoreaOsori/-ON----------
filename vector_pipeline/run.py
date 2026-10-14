import argparse
import json

from bundle import prepare, validate_bundle


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
    check = sub.add_parser("validate")
    check.add_argument("--input", required=True)
    sub.add_parser("init-db", help="RDS 준비 후 명시적 초기화. v1 DB 자동 변경 없음")
    sub.add_parser("create-index", help="대량 적재 후 명시적으로 HNSW 생성")
    for name in ("embed", "ingest"):
        command = sub.add_parser(name, help="Bedrock 임베딩·캐시" if name == "embed" else "캐시 → RDS 배치 적재, 임베딩 호출 없음")
        command.add_argument("--input", required=True)
        command.add_argument("--cache", default="output/embedding-cache.sqlite")
        command.add_argument("--batch-size", type=int, default=128)
        if name == "embed":
            command.add_argument("--workers", type=int, default=4)
        else:
            command.add_argument("--publish", action="store_true", help="전체 bundle 검증 후 활성 스냅샷 전환")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args)
    elif args.command == "validate":
        _, result = validate_bundle(args.input)
    else:
        from config import EmbeddingConfig
        config = EmbeddingConfig.from_env()
        if args.command in ("init-db", "create-index"):
            from vector_store import create_index, init_db
            (init_db if args.command == "init-db" else create_index)(config)
            result = {"command": args.command, "embedding_version": config.version}
        else:
            if not 1 <= args.batch_size <= 1000:
                parser.error("batch-size는 1~1000이어야 합니다.")
            root, manifest = validate_bundle(args.input)
            if args.command == "embed":
                if not 1 <= args.workers <= 32:
                    parser.error("workers는 1~32이어야 합니다.")
                from embed_pipeline import embed_bundle
                from embedding import BedrockEmbedder
                result = embed_bundle(root, manifest, config, BedrockEmbedder(config), args.cache, args.workers, args.batch_size)
            else:
                from vector_store import ingest
                result = ingest(root, manifest, config, args.cache, args.batch_size, args.publish)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
