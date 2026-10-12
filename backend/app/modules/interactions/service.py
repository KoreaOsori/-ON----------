"""병용금기 확인. 현재는 목업 규칙이며, DUR(의약품안전사용서비스) API 연동 시 교체한다.

TODO
- DUR 병용금기 API 조회 결과를 dur_content 에 원문 그대로 담는다.
- easy_explanation 은 Bedrock Claude 로 DUR 원문을 쉬운 말로 풀어 쓴다 (원문은 반드시 함께 노출).
"""

from itertools import combinations

from app.modules.interactions.schemas import InteractionPair
from app.modules.medicines.mock_data import MOCK_CONTRAINDICATED_PAIRS
from app.modules.medicines.service import MedicineRepository


async def check_pairs(repository: MedicineRepository, medicine_ids: list[str]) -> list[InteractionPair]:
    names = {}
    for medicine_id in medicine_ids:
        medicine = await repository.get(medicine_id)
        names[medicine_id] = medicine.name if medicine else medicine_id

    pairs = []
    for first, second in combinations(dict.fromkeys(medicine_ids), 2):
        contraindicated = frozenset({first, second}) in MOCK_CONTRAINDICATED_PAIRS
        pairs.append(
            InteractionPair(
                first=names[first],
                second=names[second],
                contraindicated=contraindicated,
                dur_content="가상의 성분 간 병용 제한 내용입니다. 실제 DUR 데이터가 아닙니다."
                if contraindicated
                else None,
                easy_explanation="두 약을 함께 복용하기 전에 약사·의사에게 확인해 주세요."
                if contraindicated
                else None,
            )
        )
    return pairs
