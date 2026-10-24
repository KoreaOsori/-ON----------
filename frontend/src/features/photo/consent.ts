import { disclaimer } from "@/lib/constants"

// 알약 사진 저장 동의 문구 (체크박스 옆). 처방전·약봉투는 어떤 것도 저장하지 않으므로 동의 항목 없음
export const cropConsentLines = [
  "(선택) 알약 사진 저장에 동의합니다.",
  "인식 정확도를 높이기 위해 배경을 제거한 알약 부분만 저장합니다. 원본 사진과 사용자 정보는 저장하지 않습니다.",
  "동의하지 않아도 알약 검색은 그대로 이용할 수 있습니다.",
  disclaimer,
]
