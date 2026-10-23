"""
pytest 공용 준비.

- 단위 테스트(test_api.py 등): 무거운 모델 없이 가짜 모듈로 API 흐름·인증·세션·저장 정책을 확인
- 통합 테스트(test_models.py): deploy/ 와 fixture 사진이 있을 때만 실제 모델로 API 를 끝까지 호출
실행 (컨테이너 안, /app): python -m pytest -q
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN = "test-token"


def put_upload(root, purpose, data, ext="png"):
    """LOCAL_UPLOAD_DIR 아래에 백엔드 presign 과 같은 형식의 key 로 사진을 둔다 → key"""
    key = f"{purpose}/2026/10/23/guest/{uuid.uuid4()}.{ext}"
    path = Path(root, *key.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


@pytest.fixture
def env(tmp_path, monkeypatch):
    up = tmp_path / "uploads"
    up.mkdir()
    for k, v in dict(WORKER_TOKEN=TOKEN, LOCAL_UPLOAD_DIR=str(up), DATA_BUCKET="", UPLOAD_BUCKET="", MODEL_BUCKET="",
                     LOAD_LLM="false", SESSION_TTL_SEC="600").items():
        monkeypatch.setenv(k, v)
    return up


HEADERS = {"X-Worker-Token": TOKEN}
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
