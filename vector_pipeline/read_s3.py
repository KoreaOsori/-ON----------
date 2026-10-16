import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from config import settings


@contextmanager
def parquet_source(uri):
    """Download exact S3 object to temporary disk; local paths work offline."""
    import pyarrow.parquet as pq

    if not uri.startswith("s3://"):
        yield pq.ParquetFile(Path(uri)), {"uri": str(Path(uri).resolve())}
        return
    import boto3
    from botocore.config import Config

    parsed = urlsplit(uri)
    if not parsed.netloc or not parsed.path.strip("/") or parsed.query:
        raise ValueError("S3 경로는 s3://bucket/exact/key.parquet 형식이어야 합니다.")
    client = boto3.client("s3", region_name=settings()["aws"]["region"],
                          config=Config(retries={"mode": "standard", "max_attempts": 5}))
    key = parsed.path.lstrip("/")
    head = client.head_object(Bucket=parsed.netloc, Key=key)
    # Current EC2 role grants GetObject, not GetObjectVersion. Read the current
    # object conditionally and record the version actually returned by S3.
    args = {"Bucket": parsed.netloc, "Key": key, "IfMatch": head["ETag"]}
    with TemporaryDirectory() as temp:
        dest = Path(temp) / "data.parquet"
        obj = client.get_object(**args)
        try:
            with dest.open("wb") as out:
                for block in obj["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
                    out.write(block)
        finally:
            obj["Body"].close()
        yield pq.ParquetFile(dest), {"uri": uri, "etag": head["ETag"],
                                    "version_id": obj.get("VersionId")}
