"""질문 임베딩 (강의의 Bedrock 임베딩 호출에 해당).

적재 때(vector_pipeline/embedding.py)와 같은 조건이어야 같은 벡터 공간에서 비교된다.
  모델 amazon.titan-embed-text-v2:0 · 1024차원 · normalize=true
boto3 는 동기 라이브러리라 asyncio.to_thread 로 감싸서 이벤트 루프를 막지 않는다.
"""
import asyncio
import json
import math
from typing import Any

from app.llm.v2.config import V2Settings

MAX_QUERY_CHARS = 1000


class EmbeddingError(Exception):
    """임베딩 실패. 질문 원문은 메시지에 넣지 않는다."""


def validate_vector(vector: list[float], dimensions: int) -> None:
    if len(vector) != dimensions or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in vector):
        raise ValueError("임베딩 차원 또는 숫자 값이 잘못되었습니다.")
    if not any(vector):
        raise ValueError("0 벡터는 코사인 검색에 사용할 수 없습니다.")


def to_vector_text(vector: list[float]) -> str:
    """pgvector 텍스트 입력 형식 '[v1,v2,...]'. SQL 에서는 CAST(:q AS vector) 로 변환한다."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class QueryEmbedder:
    def __init__(self, settings: V2Settings, client: Any = None) -> None:
        self._settings = settings
        self._client = client  # 테스트용 주입 또는 지연 생성

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._settings.region,
                config=Config(
                    retries={"mode": "adaptive", "max_attempts": 3},
                    connect_timeout=5,
                    read_timeout=20,
                    max_pool_connections=10,
                ),
            )
        return self._client

    def _embed_sync(self, text: str) -> list[float]:
        response = self._bedrock().invoke_model(
            modelId=self._settings.embedding_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {"inputText": text, "dimensions": self._settings.embedding_dimensions, "normalize": True}
            ),
        )
        try:
            vector = json.loads(response["body"].read())["embedding"]
        finally:
            response["body"].close()
        validate_vector(vector, self._settings.embedding_dimensions)
        return vector

    async def embed(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            raise EmbeddingError("빈 질문은 임베딩할 수 없습니다.")
        try:
            return await asyncio.to_thread(self._embed_sync, text[:MAX_QUERY_CHARS])
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"질문 임베딩에 실패했습니다({type(exc).__name__}).") from None
