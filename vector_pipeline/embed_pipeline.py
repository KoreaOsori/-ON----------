from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from bundle import batched, records, verify_files
from cache import EmbeddingCache


def fill_cache(documents, cache, embedder, workers=4):
    """Bound in-flight calls; commit each success even if another future fails."""
    if not 1 <= workers <= 32:
        raise ValueError("workers는 1~32이어야 합니다.")
    iterator = iter(documents)
    count = 0
    failure = None
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
                    cache.put(content_hash, future.result())
                    count += 1
                except Exception as error:
                    failure = failure or error
            if failure is None:
                for _ in completed:
                    submit_next()
    if failure is not None:
        raise RuntimeError("임베딩 일부가 실패했습니다. 저장된 성공 결과는 재실행 시 재사용됩니다.") from failure
    return count


def embed_bundle(root, manifest, config, embedder, cache_path, workers=4, batch_size=128):
    embedded = reused = 0
    with EmbeddingCache(cache_path, config) as cache:
        for batch in batched(records(root / "documents.jsonl"), batch_size):
            existing = cache.get_many([d["content_hash"] for d in batch])
            missing = [d for d in batch if d["content_hash"] not in existing]
            reused += len(existing)
            embedded += fill_cache(missing, cache, embedder, workers)
            if (embedded + reused) % (batch_size * 10) == 0:
                print(f"embeddings: {embedded:,} created, {reused:,} reused", flush=True)
    verify_files(root, manifest)
    return {"embedded": embedded, "reused": reused}
