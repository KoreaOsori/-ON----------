"""로컬 silver → S3 업로드. silver/_latest.json 에 적힌 스냅샷만 올린다.

  python pipeline/silver/upload.py                       # 기본 버킷 (pill-check-data-...)
  python pipeline/silver/upload.py --bucket 다른버킷

- 올리는 것: silver/{table}/snapshot={날짜}/ 의 파일 전부 (data.parquet, _meta.json, _rejects.json) + silver/_latest.json
- _latest.json 은 데이터 파일이 모두 올라가고 크기 확인까지 끝난 뒤 마지막에 올린다
  (읽는 쪽이 아직 없는 파일을 가리키는 포인터를 보지 않도록)
- 같은 스냅샷 폴더에 S3 에만 있는 파일(예: 이전 빌드의 _rejects.json)은 지워 로컬과 맞춘다. 버킷 버전 관리로 30일 안에는 복구 가능
- AWS 인증: EC2 는 역할, 내 PC 는 aws configure 한 계정
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "s3"
DEFAULT_BUCKET = "pill-check-data-827913617635"
REGION = "us-east-1"
PREFIX = "silver"


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def upload_silver(root, bucket):
    import boto3

    silver = Path(root) / "silver"
    latest_path = silver / "_latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    s3 = boto3.client("s3", region_name=REGION)
    log(f"silver 스냅샷 {latest['tables']} → s3://{bucket}/{PREFIX}/")

    for table, snapshot in latest["tables"].items():
        local_dir = silver / table / f"snapshot={snapshot}"
        prefix = f"{PREFIX}/{table}/snapshot={snapshot}/"
        files = sorted(p for p in local_dir.iterdir() if p.is_file() and not p.name.endswith(".tmp"))
        if not any(p.name == "data.parquet" for p in files):
            raise FileNotFoundError(f"{local_dir} 에 data.parquet 없음")
        for path in files:
            key = prefix + path.name
            s3.upload_file(str(path), bucket, key)
            remote_size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
            if remote_size != path.stat().st_size:
                raise RuntimeError(f"s3://{bucket}/{key} 크기 {remote_size} != 로컬 {path.stat().st_size}")
            log(f"  {key} ({path.stat().st_size:,} bytes)")
        local_names = {p.name for p in files}
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
        stale = [o["Key"] for o in listed.get("Contents", []) if o["Key"][len(prefix):] not in local_names]
        for key in stale:
            s3.delete_object(Bucket=bucket, Key=key)
            log(f"  {key} 삭제 (로컬에 없는 파일)")

    key = f"{PREFIX}/_latest.json"
    s3.upload_file(str(latest_path), bucket, key)
    log(f"  {key} (마지막)")
    return latest


def main():
    parser = argparse.ArgumentParser(description="silver → S3 업로드")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    args = parser.parse_args()
    try:
        latest = upload_silver(args.root, args.bucket)
    except Exception as error:  # noqa: BLE001 — 인증·권한·네트워크 등 원인과 상관없이 실패로 끝낸다
        log(f"S3 업로드 실패: {type(error).__name__}: {error}")
        sys.exit(1)
    log(f"완료 (snapshot {latest['snapshot']}, 작성 {latest['written_at']})")


if __name__ == "__main__":
    main()
