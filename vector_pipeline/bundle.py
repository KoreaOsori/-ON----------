"""Versioned, validated offline artifacts. No AWS/DB imports on local paths."""
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from build_documents import build_documents, digest
from chunking import split_text
from read_s3 import parquet_source

FORMAT_VERSION = 2
DOC_FIELDS = ("content_hash", "content", "product_type", "section_type")


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def records(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def batched(items, size):
    if not 1 <= size <= 1000:
        raise ValueError("batch_size는 1~1000이어야 합니다.")
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def prepare(args):
    list(split_text("validation", args.max_chars, args.overlap))
    if not 0 < args.min_chars <= args.max_chars or args.limit < 0:
        raise ValueError("min_chars 또는 limit이 잘못되었습니다.")
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    names = ("documents.jsonl", "links.jsonl", "rejects.jsonl")
    if any((root / n).exists() for n in (*names, "manifest.json")):
        raise ValueError("기존 결과가 있습니다. 새로운 출력 폴더를 지정하세요.")
    counts, sources, snapshots, hashes = Counter(), {}, set(), set()
    links = characters = rejected = 0
    try:
        with (root / "documents.jsonl.partial").open("w", encoding="utf-8", newline="\n") as docs, \
                (root / "links.jsonl.partial").open("w", encoding="utf-8", newline="\n") as mapping, \
                (root / "rejects.jsonl.partial").open("w", encoding="utf-8", newline="\n") as rejects:
            for kind, uri in (("drug", args.drug), ("health_food", args.health_food)):
                seen = set()
                with parquet_source(uri) as (parquet, identity):
                    sources[kind] = {**identity, "source_rows": parquet.metadata.num_rows}
                    if not parquet.metadata.num_rows:
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
                            if getattr(args, "expected_snapshot", None) and snapshot != args.expected_snapshot:
                                raise ValueError("Parquet snapshot이 Silver 완료 포인터와 다릅니다.")
                            snapshots.add(snapshot)
                            if len(snapshots) != 1:
                                raise ValueError("두 소스의 snapshot이 같아야 합니다.")
                            def on_reject(error):
                                nonlocal rejected
                                rejected += 1
                                rejects.write(json.dumps({"product_key": f"{kind}:{product_id}", "source": uri,
                                                          **error}, ensure_ascii=False) + "\n")

                            for chunk in build_documents(row, kind, uri, args.max_chars, args.overlap, args.min_chars, on_reject):
                                if chunk["content_hash"] not in hashes:
                                    hashes.add(chunk["content_hash"])
                                    docs.write(json.dumps({k: chunk[k] for k in DOC_FIELDS}, ensure_ascii=False) + "\n")
                                    characters += len(chunk["content"])
                                chunk.pop("content")
                                mapping.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                                counts[f"{kind}:{chunk['section_type']}"] += 1
                                links += 1
                            if len(seen) % 5000 == 0:
                                print(f"{kind}: {len(seen):,} products; {len(hashes):,} unique documents", flush=True)
                        if args.limit and len(seen) >= args.limit:
                            break
                    sources[kind]["processed_rows"] = len(seen)
        manifest = {"format_version": FORMAT_VERSION, "complete": not bool(args.limit) and rejected == 0,
                    "rejected_rules": rejected,
                    "snapshot": next(iter(snapshots)), "sources": sources, "documents": len(hashes),
                    "links": links, "counts": dict(counts), "embedding_characters": characters,
                    "max_chars": args.max_chars, "min_chars": args.min_chars, "overlap": args.overlap,
                    "files": {n: file_hash(root / (n + ".partial")) for n in names}}
        for n in names:
            (root / (n + ".partial")).replace(root / n)
        (root / "manifest.json.partial").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "manifest.json.partial").replace(root / "manifest.json")
        return manifest
    finally:
        for n in (*names, "manifest.json"):
            (root / (n + ".partial")).unlink(missing_ok=True)


def verify_files(root, manifest):
    if set(manifest["files"]) not in ({"documents.jsonl", "links.jsonl"}, {"documents.jsonl", "links.jsonl", "rejects.jsonl"}):
        raise ValueError("잘못된 bundle 파일 목록")
    for name, expected in manifest["files"].items():
        if file_hash(Path(root) / name) != expected:
            raise ValueError(f"파일 해시 불일치: {name}")


def validate_bundle(folder):
    root = Path(folder)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("v2 bundle이 필요합니다. 이전 결과를 새 폴더에 다시 prepare 하세요.")
    verify_files(root, manifest)
    rejected = sum(1 for _ in records(root / "rejects.jsonl")) if "rejects.jsonl" in manifest["files"] else 0
    if rejected != manifest.get("rejected_rules", 0) or (rejected and manifest["complete"]):
        raise ValueError("격리된 규칙 수 또는 complete 상태 불일치")
    date.fromisoformat(manifest["snapshot"])
    if set(manifest["sources"]) != {"drug", "health_food"} or not isinstance(manifest["complete"], bool):
        raise ValueError("소스 또는 complete 값 불일치")
    for source in manifest["sources"].values():
        if not 0 < source["processed_rows"] <= source["source_rows"]:
            raise ValueError("잘못된 제품 수")
        if manifest["complete"] and source["processed_rows"] != source["source_rows"]:
            raise ValueError("전체 스냅샷 행 수 불일치")
    docs = {}
    characters = 0
    for d in records(root / "documents.jsonl"):
        h = d["content_hash"]
        if h in docs or not d["content"].strip() or digest(d["content"]) != h:
            raise ValueError("문서 중복 또는 본문 해시 불일치")
        docs[h] = (d["product_type"], d["section_type"])
        characters += len(d["content"])
    seen, referenced, products, counts = set(), set(), {"drug": set(), "health_food": set()}, Counter()
    for c in records(root / "links.jsonl"):
        kind = c["product_type"]
        if kind not in products or not c["source_product_id"] or not c["product_name"] or not c["source_refs"]:
            raise ValueError("필수 링크 값 누락")
        if c["product_key"] != f"{kind}:{c['source_product_id']}" or c["chunk_id"] in seen:
            raise ValueError("제품 연결키 불일치 또는 중복 링크")
        if docs.get(c["content_hash"]) != (kind, c["section_type"]) or c["snapshot"] != manifest["snapshot"]:
            raise ValueError("문서 참조 또는 스냅샷 불일치")
        seen.add(c["chunk_id"])
        referenced.add(c["content_hash"])
        products[kind].add(c["source_product_id"])
        counts[f"{kind}:{c['section_type']}"] += 1
    if (not docs or len(docs) != manifest["documents"] or len(seen) != manifest["links"]
            or referenced != docs.keys() or dict(counts) != manifest["counts"]
            or characters != manifest["embedding_characters"]):
        raise ValueError("bundle 집계 불일치")
    if any(len(products[k]) != manifest["sources"][k]["processed_rows"] for k in products):
        raise ValueError("제품 수 불일치")
    return root, manifest
