"""One-shot synchronization; schedule this command externally when needed."""
from argparse import Namespace
from pathlib import Path
from tempfile import mkdtemp

from aws_runtime import silver_sources
from bundle import prepare, validate_bundle
from config import EmbeddingConfig, settings
from embed_pipeline import embed_bundle
from embedding import BedrockEmbedder
from vector_store import ingest, connect, check_config


def sync_silver(args):
    if not 1 <= args.workers <= 32 or not 1 <= args.batch_size <= 1000:
        raise ValueError("workers는 1~32, batch-size는 1~1000이어야 합니다.")
    config = EmbeddingConfig.from_env()
    # Fail before paid embedding calls if the database/schema is unavailable.
    with connect() as conn:
        check_config(conn, config)
    silver = settings()["silver"]
    sources = silver_sources(silver["bucket"], silver["prefix"])
    snapshot = sources["drug_product"].split("/")[-2].removeprefix("snapshot=")
    Path(args.output).mkdir(parents=True, exist_ok=True)
    folder = mkdtemp(prefix=f"{snapshot}-", dir=args.output)
    # Fresh preparation catches same-date source corrections; the shared cache
    # reuses identical document embeddings across snapshots and interrupted runs.
    prepare(Namespace(drug=sources["drug_product"], health_food=sources["health_food_product"],
                      output=folder, expected_snapshot=snapshot, max_chars=1800,
                      min_chars=900, overlap=150, limit=0))
    root, manifest = validate_bundle(folder)
    if not manifest["complete"]:
        raise ValueError(f"격리 규칙이 있어 공개하지 않습니다. bundle: {folder}")
    result = embed_bundle(root, manifest, config, BedrockEmbedder(config), args.cache,
                          args.workers, args.batch_size, args.retry_failed)
    if not result["complete"]:
        return {**result, "bundle": folder, "snapshot": snapshot, "published": False}
    loaded = ingest(root, manifest, config, args.cache, args.batch_size, publish=True)
    return {"complete": True, "published": True, "snapshot": snapshot,
            "bundle": folder, "ingest": loaded}
