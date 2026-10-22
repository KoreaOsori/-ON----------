"""병용금기 확인. 데이터 파이프라인의 gold.drug_contraindication 기준 (docs: gold 판정 규칙)

- 품목 DUR(식약처 품목표) 근거가 있으면 "금기", 성분 규칙 근거만 있으면 "성분 기준 주의"
- 판매중지 약은 공식 DUR 판정이 없으므로 따로 표시한다
- 어떤 경우에도 "안전"이라고 판정하지 않는다 (근거가 없으면 contraindicated=False 일 뿐)

TODO
- easy_explanation 은 Bedrock Claude 로 DUR 원문을 쉬운 말로 풀어 쓴다 (원문은 반드시 함께 노출).
"""

from itertools import combinations

from app.modules.interactions.schemas import ContraindicationDetail, InteractionPair
from app.modules.medicines.service import MedicineRepository

LEVEL_BY_BASIS = {"품목 DUR": "금기", "성분 규칙": "성분 기준 주의"}


async def check_pairs(repository: MedicineRepository, medicine_ids: list[str]) -> list[InteractionPair]:
    medicine_ids = list(dict.fromkeys(medicine_ids))
    names, discontinued = {}, set()
    for medicine_id in medicine_ids:
        medicine = await repository.get(medicine_id)
        names[medicine_id] = medicine.name if medicine else medicine_id
        if medicine and medicine.sale_status == "판매중지":
            discontinued.add(medicine_id)

    rows = await repository.contraindications(medicine_ids)

    pairs = []
    for first, second in combinations(medicine_ids, 2):
        pair_rows = [row for row in rows if row.item_seq == first and row.mixture_item_seq == second]
        bases = {row.basis for row in pair_rows}
        level = (
            LEVEL_BY_BASIS["품목 DUR"] if "품목 DUR" in bases else LEVEL_BY_BASIS.get(next(iter(bases), ""))
        )
        pairs.append(
            InteractionPair(
                first=names[first],
                second=names[second],
                contraindicated=bool(pair_rows),
                level=level,
                details=[
                    ContraindicationDetail(
                        basis=row.basis,
                        first_ingredients=row.ingr_names,
                        second_ingredients=row.mixture_ingr_names,
                        content=row.prohbt_content,
                        remark=row.remark,
                    )
                    for row in pair_rows
                ],
                discontinued=[names[item] for item in (first, second) if item in discontinued],
            )
        )
    return pairs
