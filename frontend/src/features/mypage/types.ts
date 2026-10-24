export type MyPageViewName = "home" | "consent" | "profile" | "calendar" | "notifications" | "settings"

/** 약봉투·처방전 인식(OCR) 단계: 0 닫힘, 1 촬영, 2 인식 중, 3 결과 확인, 4 완료 */
export type OcrStep = 0 | 1 | 2 | 3 | 4

export type MedicationDraft = {
  name: string
  amount: string
  times: string
  days: string
  start: string
}
