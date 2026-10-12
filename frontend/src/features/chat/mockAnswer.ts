// 데모용 응답 생성기. 백엔드 POST /api/v1/chat (Bedrock Claude) 연동 시 교체한다.
export function buildMockAnswer(question: string, drug: string | null) {
  if (!drug)
    return "어떤 약에 대해 궁금하신가요? 약 이름을 알려주시면 관련 정보를 안내할게요. 데모에서는 가나다정, 라마바정, 사아자정, 차카타정, 마바사정을 검색할 수 있어요."
  if (question.includes("임산부") || question.includes("어린이"))
    return `${drug}의 임산부·어린이 복용 안내를 확인하는 가상 예시예요. 실제 복용 가능 여부를 판단할 수 없으며, 임신 여부와 연령에 따른 안내는 약사·의사와 상담해 주세요.`
  if (question.includes("함께") || question.includes("병용"))
    return `${drug}의 병용 정보를 확인하는 가상 예시예요. 함께 복용할 다른 약 이름을 알려주거나 약정보 메뉴의 병용 확인을 이용해 주세요.`
  return `${drug}에 대한 가상의 안내예요. 효능·효과, 복용 방법, 주의사항을 확인하는 화면 예시입니다. 실제 복용 시간과 용량은 처방전 또는 약봉투를 확인하고 약사·의사와 상담해 주세요.`
}
