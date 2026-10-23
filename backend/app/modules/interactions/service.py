"""병용금기 확인. 데이터 파이프라인의 gold.drug_contraindication 기준 (docs: gold 판정 규칙)

- 품목 DUR(식약처 품목표) 근거가 있으면 "금기", 성분 규칙 근거만 있으면 "성분 기준 주의"
- 판매중지 약은 공식 DUR 판정이 없으므로 따로 표시한다
- 어떤 경우에도 "안전"이라고 판정하지 않는다 (근거가 없으면 contraindicated=False 일 뿐)

TODO
- easy_explanation 은 Bedrock Claude 로 DUR 원문을 쉬운 말로 풀어 쓴다 (원문은 반드시 함께 노출).
"""

from itertools import combinations

from app.modules.interactions.schemas import (
    ContraindicationDetail,
    DuplicateCaution,
    DuplicateMedicine,
    InteractionPair,
    MedicineCautions,
)
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


async def collect_cautions(repository: MedicineRepository, medicine_ids: list[str]) -> list[MedicineCautions]:
    """고른 약마다 DUR 주의 (약 상세와 같은 것)와 허가 문서의 "투여하지 말 것" 환자 항목.
    프로필이 없어도 DUR 주의는 보여주고, 지병과 맞추는 일은 화면에서 한다"""
    result = []
    for medicine_id in dict.fromkeys(medicine_ids):
        medicine = await repository.get(medicine_id)
        if medicine and (medicine.dur_cautions or medicine.contraindicated_patients):
            result.append(
                MedicineCautions(
                    name=medicine.name,
                    cautions=medicine.dur_cautions,
                    contraindicated_patients=medicine.contraindicated_patients,
                )
            )
    return result


async def check_duplicates(repository: MedicineRepository, medicine_ids: list[str]) -> list[DuplicateCaution]:
    """같은 성분 또는 같은 효능군 계열이 2개 이상의 약에 있으면 주의로 알린다 (병용금기 아님)"""
    medicine_ids = list(dict.fromkeys(medicine_ids))
    names = {}
    for medicine_id in medicine_ids:
        medicine = await repository.get(medicine_id)
        names[medicine_id] = medicine.name if medicine else medicine_id
    rows = await repository.ingredients(medicine_ids)
    daily_max = {row.ingr_key: row.daily_max for row in rows}
    ingredient_name = {row.ingr_key: row.ingr_name for row in rows}

    def caution(kind, name, matched):
        keys = list(dict.fromkeys(row.ingr_key for row in matched))
        return DuplicateCaution(
            kind=kind,
            name=name,
            medicines=[
                DuplicateMedicine(
                    name=names[item],
                    ingredients=list(dict.fromkeys(row.ingr_name for row in matched if row.item_seq == item)),
                )
                for item in medicine_ids
                if any(row.item_seq == item for row in matched)
            ],
            daily_max=[text for key in keys for text in daily_max[key]],
        )

    cautions = []
    for key in dict.fromkeys(row.ingr_key for row in rows):
        matched = [row for row in rows if row.ingr_key == key]
        if len({row.item_seq for row in matched}) >= 2:
            cautions.append(caution("같은 성분", ingredient_name[key], matched))
    for group in dict.fromkeys(row.efficacy_group for row in rows if row.efficacy_group):
        matched = [row for row in rows if row.efficacy_group == group]
        # 같은 성분만 겹친 경우는 위에서 이미 알렸다. 계열 안에서 성분이 서로 다를 때만
        if len({row.item_seq for row in matched}) >= 2 and len({row.ingr_key for row in matched}) >= 2:
            cautions.append(caution("같은 계열", group, matched))
    return cautions
