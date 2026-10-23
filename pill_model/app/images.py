"""
낱알 공식 사진 URL — silver drug_product 의 item_seq·pills 두 컬럼만 S3 범위 읽기 (plan.md 3-1 ④).

파일 전체(370MB)를 받지 않는다: t3.medium 4GB 보호. 실측(10-23) 약 14.5초 · 메모리 7.7MB.
실패해도 서비스는 시작하고 image_url=null, /health 에 상태를 보여준다.
"""
import json
import logging
import time

log = logging.getLogger("pill_worker.images")


def pick_urls(seqs, pills_col):
    """품목별 첫 사진: image_id 순 첫 장 (파이프라인 정렬과 같음), item_image 빈 값은 건너뜀"""
    out = {}
    for seq, pills in zip(seqs, pills_col):
        if not seq or not pills:
            continue
        rows = sorted((p for p in pills if p and p.get("item_image")), key=lambda p: str(p.get("image_id") or ""))
        if rows:
            out[str(seq)] = rows[0]["item_image"]
    return out


class ImageIndex:
    def __init__(self):
        self.urls = {}
        self.status = "not_loaded"
        self.snapshot = None
        self.error = None
        self.load_sec = None

    def url(self, item_seq):
        return self.urls.get(str(item_seq))

    def load(self, bucket, region):
        if not bucket:
            self.status = "disabled"
            return
        t = time.time()
        self.status = "loading"
        try:
            import boto3
            import pyarrow.parquet as pq
            from pyarrow import fs as pafs
            latest = json.loads(boto3.client("s3", region_name=region)
                                .get_object(Bucket=bucket, Key="silver/_latest.json")["Body"].read())
            snap = latest["tables"]["drug_product"]
            path = f"{bucket}/silver/drug_product/snapshot={snap}/data.parquet"
            table = pq.read_table(path, columns=["item_seq", "pills"], filesystem=pafs.S3FileSystem(region=region))
            self.urls = pick_urls(table.column("item_seq").to_pylist(), table.column("pills").to_pylist())
            self.snapshot, self.status = snap, "ok"
        except Exception as e:  # 권한·네트워크 문제여도 식별 기능은 계속 동작
            self.status, self.error = "error", type(e).__name__
            log.warning("image index load failed: %s", type(e).__name__)
        self.load_sec = round(time.time() - t, 1)
        log.info("image index: status=%s size=%d sec=%s", self.status, len(self.urls), self.load_sec)
