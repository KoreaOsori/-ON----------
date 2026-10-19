"""파이프라인 공통: S3 데이터 버킷 읽기·쓰기. bronze·silver·gold 의 원본은 S3 이고, 디스크는 빌드할 때만 쓰는 임시 폴더다.

경로: bronze/{서비스}/{오퍼레이션}/snapshot={날짜}/page_00001.json, _manifest.json
      silver/{테이블}/snapshot={날짜}/data.parquet, _meta.json, _rejects.json + silver/_latest.json
      gold/{테이블}/snapshot={silver 날짜}/data.parquet + gold/_latest.json

- 버킷은 각 스크립트의 --bucket 으로 바꾼다. 로컬 시험은 환경변수 AWS_ENDPOINT_URL_S3 로 시험용 S3(moto)를 가리킨다
- AWS 인증: EC2 는 역할, 내 PC 는 aws configure 한 계정
"""

import json
from pathlib import Path

DEFAULT_BUCKET = "pill-check-data-827913617635"
REGION = "us-east-1"


class Store:
    def __init__(self, bucket=DEFAULT_BUCKET):
        import boto3

        self.bucket = bucket
        self.s3 = boto3.client("s3", region_name=REGION)

    def list(self, prefix):
        """prefix 아래 객체 {키: 크기}."""
        found = {}
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                found[obj["Key"]] = obj["Size"]
        return found

    def folders(self, prefix):
        """prefix 바로 아래 폴더 이름 목록 (prefix 는 / 로 끝나야 한다)."""
        names = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix, Delimiter="/"):
            names += [p["Prefix"][len(prefix):].rstrip("/") for p in page.get("CommonPrefixes", [])]
        return names

    def get_json(self, key):
        """JSON 객체. 없으면 None."""
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None
        return json.loads(body)

    def put_json(self, key, payload):
        self.s3.put_object(Bucket=self.bucket, Key=key, ContentType="application/json",
                           Body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))

    def download_prefix(self, prefix, local_dir):
        """prefix 아래 파일을 local_dir 로 받는다 (같은 크기 파일이 이미 있으면 건너뜀). 받은 파일 수를 돌려준다."""
        objects = self.list(prefix)
        for key, size in objects.items():
            path = Path(local_dir) / key[len(prefix):]
            if path.exists() and path.stat().st_size == size:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, key, str(path))
            if path.stat().st_size != size:
                raise RuntimeError(f"s3://{self.bucket}/{key} 받은 크기 {path.stat().st_size} != {size}")
        return len(objects)

    def upload_file(self, path, key):
        self.s3.upload_file(str(path), self.bucket, key)
        remote = self.s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        if remote != Path(path).stat().st_size:
            raise RuntimeError(f"s3://{self.bucket}/{key} 크기 {remote} != 로컬 {Path(path).stat().st_size}")

    def upload_dir(self, local_dir, prefix, log=print):
        """local_dir 의 파일(.tmp 제외)을 prefix 아래로 올리고, prefix 에만 있는 옛 파일은 지운다 (버킷 버전 관리로 30일 복구 가능)."""
        files = sorted(p for p in Path(local_dir).iterdir() if p.is_file() and not p.name.endswith(".tmp"))
        for path in files:
            self.upload_file(path, prefix + path.name)
            log(f"  s3://{self.bucket}/{prefix}{path.name} ({path.stat().st_size:,} bytes)")
        names = {p.name for p in files}
        for key in self.list(prefix):
            if key[len(prefix):] not in names:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
                log(f"  s3://{self.bucket}/{key} 삭제 (이번 결과에 없는 파일)")
