"""처방전·약봉투 인식. OCR_PROVIDER 로 구현을 선택한다.

- mock     : 고정된 예시 결과
- claude   : Bedrock Claude 비전으로 이미지에서 복용약 정보를 구조화 추출 (한국어 지원, 권장)
- textract : AWS Textract 텍스트 추출. ⚠ Textract 는 한국어를 지원하지 않아 한글 처방전에는 부적합
"""

import base64
import json
import logging

from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from app.core.config import settings
from app.integrations import bedrock
from app.integrations.aws import s3_client, textract_client
from app.modules.ocr.schemas import MedicationCandidate

logger = logging.getLogger(__name__)

# Bedrock(Mantle)은 structured outputs 미지원 → 프롬프트로 JSON 형식을 지정하고 방어적으로 파싱한다
OCR_SYSTEM_PROMPT = """당신은 한국 처방전과 약봉투 사진에서 복용약 정보를 옮겨 적는 도우미입니다.
사진에 실제로 적힌 내용만 추출하고, 읽을 수 없는 값은 null 로 둡니다. 값을 추측하지 마세요.
설명 없이 아래 형식의 JSON 객체 하나만 출력하세요.
{"candidates": [{"name": "약 이름", "amount": 1회 복용량(정, 정수|null), "timesPerDay": 하루 횟수(정수|null), "days": 총 일수(정수|null)}]}"""


def parse_candidates(text: str) -> list[MedicationCandidate]:
    """모델 응답에서 JSON 객체를 찾아 후보 목록으로 변환한다. 형식이 어긋나면 빈 목록."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start : end + 1]).get("candidates", [])
        return [MedicationCandidate.model_validate(item) for item in items if item.get("name")]
    except (ValueError, AttributeError, ValidationError) as error:
        logger.warning("OCR 응답 파싱 실패: %s", error)
        return []


async def _claude(object_key: str) -> list[MedicationCandidate]:
    obj = await run_in_threadpool(s3_client().get_object, Bucket=settings.s3_upload_bucket, Key=object_key)
    image = base64.b64encode(obj["Body"].read()).decode()
    text = await bedrock.create_message(
        system=OCR_SYSTEM_PROMPT,
        content=[
            {"type": "image", "source": {"type": "base64", "media_type": obj["ContentType"], "data": image}},
            {"type": "text", "text": "이 사진에 있는 복용약 목록을 추출해 주세요."},
        ],
    )
    return parse_candidates(text) if text else []


async def _textract(object_key: str) -> list[MedicationCandidate]:
    result = await run_in_threadpool(
        textract_client().detect_document_text,
        Document={"S3Object": {"Bucket": settings.s3_upload_bucket, "Name": object_key}},
    )
    lines = [block["Text"] for block in result.get("Blocks", []) if block["BlockType"] == "LINE"]
    logger.info("Textract 추출 라인 수: %d", len(lines))
    # TODO: 추출 라인에서 약 이름/용법 파싱 규칙 구현
    return [MedicationCandidate(name=line) for line in lines[:10]]


async def recognize_prescription(object_key: str) -> list[MedicationCandidate]:
    if settings.ocr_provider == "claude":
        return await _claude(object_key)
    if settings.ocr_provider == "textract":
        return await _textract(object_key)
    return [MedicationCandidate(name="가나다정", amount=1, times_per_day=3, days=7)]
