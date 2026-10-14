"""Durable local checkpoint. Mount its parent directory outside the container."""
import sqlite3
import struct
from pathlib import Path

from embedding import validate_vector


class EmbeddingCache:
    def __init__(self, path, config):
        self.config = config
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS embeddings (content_hash TEXT, version TEXT, dimensions INTEGER, "
                        "vector BLOB NOT NULL, PRIMARY KEY(content_hash,version))")
        self.db.commit()

    def get_many(self, hashes):
        if not hashes:
            return {}
        placeholders = ",".join("?" for _ in hashes)
        rows = self.db.execute(f"SELECT content_hash,dimensions,vector FROM embeddings WHERE version=? AND content_hash IN ({placeholders})",
                               [self.config.version, *hashes])
        result = {}
        for h, dimensions, blob in rows:
            if dimensions != self.config.dimensions or len(blob) != dimensions * 4:
                raise ValueError("캐시 벡터 차원 불일치")
            vector = list(struct.unpack(f"<{dimensions}f", blob))
            validate_vector(vector, dimensions)
            result[h] = vector
        return result

    def put(self, content_hash, vector):
        validate_vector(vector, self.config.dimensions)
        blob = struct.pack(f"<{self.config.dimensions}f", *vector)
        with self.db:
            self.db.execute("INSERT INTO embeddings VALUES (?,?,?,?) ON CONFLICT(content_hash,version) DO UPDATE SET vector=excluded.vector, dimensions=excluded.dimensions",
                            (content_hash, self.config.version, self.config.dimensions, blob))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
