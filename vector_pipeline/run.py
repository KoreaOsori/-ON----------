import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from build_documents import build_documents, digest
from chunking import split_text
from read_s3 import parquet_source


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare(args):
    list(split_text("validation", args.max_chars, args.overlap))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    final = output / "chunks.jsonl"
    manifest_path = output / "manifest.json"
    if final.exists() or manifest_path.exists():
        raise ValueError("출력 폴더에 기존 결과가 있습니다. 새로운 출력 폴더를 지정하세요.")
    temp = output / "chunks.jsonl.partial"
    counts, sources, snapshots = Counter(), {}, set()
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            for kind, uri in (("drug", args.drug), ("health_food", args.health_food)):
                seen = set()
                with parquet_source(uri) as (parquet, identity):
                    sources[kind] = {**identity, "source_rows": parquet.metadata.num_rows}
                    if parquet.metadata.num_rows == 0:
                        raise ValueError(f"빈 소스: {kind}")
                    key = "item_seq" if kind == "drug" else "prdlst_report_no"
                    for batch in parquet.iter_batches(batch_size=128):
                        for row in batch.to_pylist():
                            if args.limit and len(seen) >= args.limit:
                                break
                            product_id = str(row.get(key) or "").strip()
                            if product_id in seen:
                                raise ValueError(f"중복 제품 ID: {kind}/{product_id}")
                            seen.add(product_id)
                            snapshot = str(row.get("snapshot"))
                            date.fromisoformat(snapshot)
                            snapshots.add(snapshot)
                            if len(snapshots) != 1:
                                raise ValueError("두 데이터의 snapshot이 같아야 합니다.")
                            for chunk in build_documents(row, kind, uri, args.max_chars, args.overlap):
                                stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                                counts[f"{kind}:{chunk['section_type']}"] += 1
                            if len(seen) % 1000 == 0:
                                print(f"{kind}: {len(seen):,} products, {sum(counts.values()):,} total chunks", flush=True)
                        if args.limit and len(seen) >= args.limit:
                            break
                    sources[kind]["processed_rows"] = len(seen)
                    print(f"{kind}: {len(seen):,} products processed", flush=True)
        manifest = {"format_version": 1, "complete": not bool(args.limit),
                    "snapshot": next(iter(snapshots)), "sources": sources,
                    "chunks": sum(counts.values()), "counts": dict(counts),
                    "max_chars": args.max_chars, "overlap": args.overlap,
                    "sha256": file_hash(temp)}
        temp.replace(final)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    finally:
        temp.unlink(missing_ok=True)


def validate_bundle(folder):
    path = Path(folder) / "chunks.jsonl"
    manifest = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or file_hash(path) != manifest["sha256"]:
        raise ValueError("manifest 버전 또는 파일 해시가 일치하지 않습니다.")
    if set(manifest["sources"]) != {"drug", "health_food"}:
        raise ValueError("두 제품군의 소스가 모두 필요합니다.")
    if not isinstance(manifest.get("complete"), bool):
        raise ValueError("잘못된 complete 값")
    if manifest["complete"] and any(s["source_rows"] != s["processed_rows"] for s in manifest["sources"].values()):
        raise ValueError("전체 스냅샷 행 수가 일치하지 않습니다.")
    seen, products, counts = set(), {"drug": set(), "health_food": set()}, Counter()
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            c = json.loads(line)
            kind = c["product_type"]
            if kind not in products or not c["source_product_id"] or not c["content"].strip():
                raise ValueError("필수 청크 값 누락")
            if c["product_key"] != f"{kind}:{c['source_product_id']}":
                raise ValueError("제품 연결키 불일치")
            if c["chunk_id"] in seen or digest(c["content"]) != c["content_hash"]:
                raise ValueError("중복 청크 또는 본문 해시 불일치")
            if c["snapshot"] != manifest["snapshot"]:
                raise ValueError("청크 스냅샷 불일치")
            seen.add(c["chunk_id"])
            products[kind].add(c["source_product_id"])
            counts[f"{kind}:{c['section_type']}"] += 1
    if not seen or len(seen) != manifest["chunks"] or dict(counts) != manifest["counts"]:
        raise ValueError("청크 집계 불일치")
    if any(len(products[k]) != manifest["sources"][k]["processed_rows"] for k in products):
        raise ValueError("제품 수 불일치")
    return path, manifest


def main():
    parser = argparse.ArgumentParser(description="S3 Silver → unified pgvector index (offline prepare supported)")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="로컬/S3 Parquet → JSONL. 임베딩·DB 호출 없음")
    prep.add_argument("--drug", required=True)
    prep.add_argument("--health-food", required=True)
    prep.add_argument("--output", required=True)
    prep.add_argument("--max-chars", type=int, default=1800)
    prep.add_argument("--overlap", type=int, default=150)
    prep.add_argument("--limit", type=int, default=0, help="제품군별 샘플 수. 0은 전체")
    check = sub.add_parser("validate")
    check.add_argument("--input", required=True)
    sub.add_parser("init-db", help="RDS 준비 후 명시적으로 테이블 생성")
    load = sub.add_parser("ingest", help="Bedrock 호출 비용 발생; RDS 필요")
    load.add_argument("--input", required=True)
    load.add_argument("--replace-snapshot", action="store_true", help="전체 스냅샷에서 사라진 제품도 제거")
    args = parser.parse_args()
    if args.command == "prepare":
        if args.limit < 0:
            parser.error("--limit은 0 이상이어야 합니다.")
        result = prepare(args)
    elif args.command == "validate":
        _, result = validate_bundle(args.input)
    else:
        from config import EmbeddingConfig
        from vector_store import init_db, ingest
        config = EmbeddingConfig.from_env()
        if args.command == "init-db":
            init_db(config)
            result = {"initialized": True, "embedding_version": config.version}
        else:
            from embedding import BedrockEmbedder
            path, manifest = validate_bundle(args.input)
            if args.replace_snapshot and not manifest["complete"]:
                parser.error("샘플 결과는 --replace-snapshot으로 사용할 수 없습니다.")
            result = ingest(path, manifest, config, BedrockEmbedder(config), args.replace_snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
