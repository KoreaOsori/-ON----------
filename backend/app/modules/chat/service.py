import re

from app.core.config import settings
from app.integrations import bedrock
from app.modules.chat.prompts import SYSTEM_PROMPT, build_user_content
from app.modules.medicines.schemas import MedicineDetail
from app.modules.medicines.service import MedicineRepository

EMERGENCY_PATTERN = re.compile(r"응급|호흡|심각|의식|쇼크|아나필락시스")
FALLBACK_ANSWER = (
    "지금은 답변을 만들기 어려워요. 약 이름을 다시 확인하시거나 가까운 약사·의사와 상담해 주세요."
)


def _medicine_context(medicine: MedicineDetail) -> str:
    return (
        f"제품명: {medicine.name} ({medicine.maker})\n"
        f"효능·효과: {medicine.efficacy}\n"
        f"용법·용량: {medicine.usage}\n"
        f"주의사항: {medicine.precautions}\n"
        f"상호작용: {medicine.interaction_summary}\n"
        f"출처: {medicine.source}"
    )


def _mock_answer(question: str, drug: str | None) -> str:
    """BEDROCK_ENABLED=false 일 때의 데모 응답 (프론트 목업과 동일)"""
    if not drug:
        return (
            "어떤 약에 대해 궁금하신가요? 약 이름을 알려주시면 관련 정보를 안내할게요. "
            "데모에서는 가나다정, 라마바정, 사아자정, 차카타정, 마바사정을 검색할 수 있어요."
        )
    if "임산부" in question or "어린이" in question:
        return (
            f"{drug}의 임산부·어린이 복용 안내를 확인하는 가상 예시예요. 실제 복용 가능 여부를 판단할 수 없으며, "
            "임신 여부와 연령에 따른 안내는 약사·의사와 상담해 주세요."
        )
    if "함께" in question or "병용" in question:
        return (
            f"{drug}의 병용 정보를 확인하는 가상 예시예요. "
            "함께 복용할 다른 약 이름을 알려주거나 약정보 메뉴의 병용 확인을 이용해 주세요."
        )
    return (
        f"{drug}에 대한 가상의 안내예요. 효능·효과, 복용 방법, 주의사항을 확인하는 화면 예시입니다. "
        "실제 복용 시간과 용량은 처방전 또는 약봉투를 확인하고 약사·의사와 상담해 주세요."
    )


async def answer_question(
    repository: MedicineRepository, question: str, profile_context: str | None
) -> tuple[str, MedicineDetail | None]:
    medicine = await repository.find_in_text(question)
    drug_name = medicine.name if medicine else None

    if not settings.bedrock_enabled:
        return _mock_answer(question, drug_name), medicine

    content = build_user_content(question, _medicine_context(medicine) if medicine else None, profile_context)
    answer = await bedrock.create_message(system=SYSTEM_PROMPT, content=content)
    return answer or FALLBACK_ANSWER, medicine


def is_emergency(question: str) -> bool:
    return bool(EMERGENCY_PATTERN.search(question))
