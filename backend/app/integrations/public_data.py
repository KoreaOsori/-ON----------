"""공공데이터포털(data.go.kr) 연동 클라이언트.

- 식약처 의약품개요정보(e약은요): DrbEasyDrugInfoService/getDrbEasyDrugList
- (TODO) 식약처 DUR 병용금기: DURPrdlstInfoService03/getUsjntTabooInfoList03
- (TODO) 국립중앙의료원 약국 위치: ErmctInsttInfoInqireService/getParmacyLcinfoInqire
"""

from typing import Any

import httpx

from app.core.config import settings

BASE_URL = "https://apis.data.go.kr"
EASY_DRUG_PATH = "/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"


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
