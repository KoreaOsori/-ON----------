from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from bundle import batched, records, verify_files
from cache import EmbeddingCache


def fill_cache(documents, cache, embedder, workers=4, continue_on_error=False):
    """Bound in-flight calls; commit each success even if another future fails."""
    if not 1 <= workers <= 32:
        raise ValueError("workers는 1~32이어야 합니다.")
    iterator = iter(documents)
    count = 0
    failure = None
    fatal = None
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}

        def submit_next():
            document = next(iterator, None)
            if document is not None:
                pending[executor.submit(embedder.embed, document["content"])] = document["content_hash"]

        for _ in range(workers):
            submit_next()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                content_hash = pending.pop(future)
                try:
                    vector = future.result()
                except Exception as error:
                    code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
                    if code in {"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException",
                                "ThrottlingException", "ServiceUnavailableException", "InternalServerException",
                                "EndpointConnectionError", "NoCredentialsError", "ReadTimeoutError", "ConnectTimeoutError"}:
                        fatal = fatal or error
                    else:
                        cache.record_failure(content_hash, error)
                        failure = failure or error
                else:
                    # Disk/cache errors are fatal, not document-level failures.
                    cache.put(content_hash, vector)
                    count += 1
            if fatal is None and (failure is None or continue_on_error):
                for _ in completed:
                    submit_next()
    if fatal is not None:
        raise RuntimeError("권한·연결·서비스 오류입니다. 문서 실패로 격리하지 않고 실행을 중단합니다.") from fatal
    if failure is not None and not continue_on_error:
        raise RuntimeError("임베딩 일부가 실패했습니다. 저장된 성공 결과는 재실행 시 재사용됩니다.") from failure
    return count


def embed_bundle(root, manifest, config, embedder, cache_path, workers=4, batch_size=128, retry_failed=False):
    embedded = reused = failed = skipped = 0
    with EmbeddingCache(cache_path, config) as cache:
        for batch in batched(records(root / "documents.jsonl"), batch_size):
            existing = cache.get_many([d["content_hash"] for d in batch])
            failures = cache.failed_hashes([d["content_hash"] for d in batch]) - existing.keys()
            skipped += len(failures) if not retry_failed else 0
            missing = [d for d in batch if d["content_hash"] not in existing
                       and (retry_failed or d["content_hash"] not in failures)]
            reused += len(existing)
            embedded += fill_cache(missing, cache, embedder, workers, continue_on_error=True)
            failed += len(cache.failed_hashes([d["content_hash"] for d in batch]))
            if (embedded + reused) % (batch_size * 10) == 0:
                print(f"embeddings: {embedded:,} created, {reused:,} reused", flush=True)
        cache.export_failures(Path(cache_path).with_suffix(".failures.jsonl"))
    verify_files(root, manifest)
    return {"embedded": embedded, "reused": reused, "failed": failed, "skipped_recorded_failures": skipped,
            "complete": failed == 0 and embedded + reused == manifest["documents"]}
