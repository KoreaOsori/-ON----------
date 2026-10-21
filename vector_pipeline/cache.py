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
        self.db.execute("CREATE TABLE IF NOT EXISTS failures (content_hash TEXT, version TEXT, error_type TEXT, "
                        "message TEXT, attempts INTEGER NOT NULL DEFAULT 1, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, "
                        "PRIMARY KEY(content_hash,version))")
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
            self.db.execute("DELETE FROM failures WHERE content_hash=? AND version=?", (content_hash, self.config.version))

    def record_failure(self, content_hash, error):
        # Body text/credentials are never copied to logs; provider code is enough for triage.
        code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
        with self.db:
            self.db.execute("INSERT INTO failures(content_hash,version,error_type,message) VALUES(?,?,?,?) "
                            "ON CONFLICT(content_hash,version) DO UPDATE SET error_type=excluded.error_type, "
                            "message=excluded.message,attempts=failures.attempts+1,updated_at=CURRENT_TIMESTAMP",
                            (content_hash, self.config.version, type(error).__name__, str(code)[:200]))

    def failed_hashes(self, hashes):
        if not hashes:
            return set()
        placeholders = ",".join("?" for _ in hashes)
        return {r[0] for r in self.db.execute(f"SELECT content_hash FROM failures WHERE version=? AND content_hash IN ({placeholders})",
                                             [self.config.version, *hashes])}

    def export_failures(self, output):
        import json
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as stream:
            for row in self.db.execute("SELECT content_hash,error_type,message,attempts,updated_at FROM failures WHERE version=? ORDER BY content_hash", (self.config.version,)):
                stream.write(json.dumps({"embedding_version": self.config.version,
                                         **dict(zip(("content_hash", "error_type", "code", "attempts", "updated_at"), row))}, ensure_ascii=False) + "\n")

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
