"""
워커 설정 — 전부 환경변수(.env)에서 읽는다. 버킷 이름·토큰 같은 값은 코드에 쓰지 않는다 (claude.md 1-3).
"""
import os
from dataclasses import dataclass


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    worker_token: str
    aws_region: str
    model_bucket: str
    data_bucket: str
    upload_bucket: str
    rembg_model: str
    deploy_dir: str
    # 테스트·PC 확인용: S3 대신 이 폴더에서 object_key 경로의 사진을 읽는다 (운영에서는 비워 둠)
    local_upload_dir: str
    # False 면 Bedrock 클라이언트를 만들지 않음 (fixture 대조·PC 테스트)
    load_llm: bool
    session_ttl_sec: int
    busy_wait_sec: float
    max_bytes: int


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        worker_token=e("WORKER_TOKEN", ""),
        aws_region=e("AWS_REGION", "us-east-1"),
        model_bucket=e("MODEL_BUCKET", ""),
        data_bucket=e("DATA_BUCKET", ""),
        upload_bucket=e("UPLOAD_BUCKET", ""),
        rembg_model=e("REMBG_MODEL", "u2netp"),
        deploy_dir=e("DEPLOY_DIR", "deploy"),
        local_upload_dir=e("LOCAL_UPLOAD_DIR", ""),
        load_llm=_bool("LOAD_LLM", True),
        # plan.md 3-2: 세션 10분, 대기 60초 넘으면 busy, 사진 10MB 이하 (백엔드 presign 상한과 같음)
        session_ttl_sec=int(e("SESSION_TTL_SEC", "600")),
        busy_wait_sec=float(e("BUSY_WAIT_SEC", "60")),
        max_bytes=int(e("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
    )
