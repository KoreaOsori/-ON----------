"""공공데이터포털(data.go.kr) 연동 클라이언트.

- 식약처 의약품개요정보(e약은요): DrbEasyDrugInfoService/getDrbEasyDrugList
- (TODO) 식약처 DUR 병용금기: DURPrdlstInfoService03/getUsjntTabooInfoList03
- 국립중앙의료원 약국 위치: ErmctInsttInfoInqireService/getParmacyLcinfoInqire (좌표 → 거리순, 오늘 영업시간)
- 국립중앙의료원 약국 기본정보: ErmctInsttInfoInqireService/getParmacyBassInfoInqire (요일별 영업시간)
"""

from typing import Any

import httpx

from app.core.config import settings

BASE_URL = "https://apis.data.go.kr"
EASY_DRUG_PATH = "/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
PHARMACY_PATH = "/B552657/ErmctInsttInfoInqireService"


class PublicDataError(Exception):
    pass


async def fetch_easy_drug_list(
    *, item_name: str | None = None, item_seq: str | None = None, rows: int = 20
) -> list[dict[str, Any]]:
    if not settings.public_data_service_key:
        raise PublicDataError("PUBLIC_DATA_SERVICE_KEY 가 설정되지 않았습니다.")
    params: dict[str, Any] = {
        "serviceKey": settings.public_data_service_key,
        "type": "json",
        "numOfRows": rows,
        "pageNo": 1,
    }
    if item_name:
        params["itemName"] = item_name
    if item_seq:
        params["itemSeq"] = item_seq
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        response = await client.get(EASY_DRUG_PATH, params=params)
    if response.status_code != 200:
        raise PublicDataError(f"e약은요 API 오류: {response.status_code}")
    body = response.json().get("body", {})
    return body.get("items") or []


async def _fetch_pharmacy_items(operation: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if not settings.public_data_service_key:
        raise PublicDataError("PUBLIC_DATA_SERVICE_KEY 가 설정되지 않았습니다.")
    query = {"serviceKey": settings.public_data_service_key, "_type": "json", **params}
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        response = await client.get(f"{PHARMACY_PATH}/{operation}", params=query)
    if response.status_code != 200:
        raise PublicDataError(f"약국 API 오류: {response.status_code}")
    try:
        body = response.json()["response"]
    except (ValueError, KeyError) as error:  # 키 오류 등은 XML 로 온다
        raise PublicDataError(f"약국 API 응답 형식 오류: {response.text[:200]}") from error
    if body["header"]["resultCode"] != "00":
        raise PublicDataError(f"약국 API 오류: {body['header']['resultMsg']}")
    items = (body["body"].get("items") or {}).get("item") or []
    # 결과가 1건이면 목록이 아니라 객체로 온다
    return items if isinstance(items, list) else [items]


async def fetch_pharmacies_near(*, lat: float, lng: float, rows: int = 30) -> list[dict[str, Any]]:
    """좌표에서 가까운 순. distance(km), startTime/endTime(오늘 영업시간)을 준다"""
    return await _fetch_pharmacy_items(
        "getParmacyLcinfoInqire", {"WGS84_LAT": lat, "WGS84_LON": lng, "pageNo": 1, "numOfRows": rows}
    )


async def fetch_pharmacy_detail(hpid: str) -> dict[str, Any] | None:
    """dutyTime{1~8}s/c: 월~일, 공휴일 영업 시작/종료 (HHMM)"""
    items = await _fetch_pharmacy_items("getParmacyBassInfoInqire", {"HPID": hpid})
    return items[0] if items else None
