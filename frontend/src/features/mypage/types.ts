import type { MedicineSummary } from "@/features/medicine/api"

export type MyPageViewName = "home" | "consent" | "profile" | "calendar" | "notifications" | "settings"

/** 약봉투·처방전 인식(OCR) 단계: 0 닫힘, 1 촬영, 2 인식 중, 3 결과 확인, 4 완료 */
export type OcrStep = 0 | 1 | 2 | 3 | 4

export type MedicationDraft = {
  name: string
  amount: string
  times: string
  days: string
  start: string
  /** 약 검색에서 고른 실제 약 (직접 입력한 이름이면 없음). 병용 확인에 불러올 때 쓴다 */
  medicine?: MedicineSummary | null
}

/** 약 등록으로 저장한 복용약과 일정 (브라우저에만 저장) */
export type RegisteredMedication = MedicationDraft & { id: string }

export const intakeSlots = ["아침 식후", "점심 식후", "저녁 식후"]

/** 하루 횟수에 따른 복용 시점: 1회 아침, 2회 아침·저녁, 3회 이상 아침·점심·저녁 */
export function slotsFor(times: string) {
  const count = Number(times)
  if (count <= 1) return [intakeSlots[0]]
  if (count === 2) return [intakeSlots[0], intakeSlots[2]]
  return intakeSlots
}

/** 그 날짜(YYYY-MM-DD)가 복용 기간(시작일부터 복용 일수만큼) 안인지 */
export function isTakingOn(medication: MedicationDraft, date: string) {
  const start = new Date(`${medication.start}T00:00:00`)
  const day = new Date(`${date}T00:00:00`)
  const elapsed = Math.round((day.getTime() - start.getTime()) / (24 * 60 * 60 * 1000))
  return elapsed >= 0 && elapsed < Number(medication.days)
}

/** 이 기기 시간 기준 날짜 문자열 (YYYY-MM-DD) */
export function toDateString(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

/** 날짜·시점마다 먹을 약 이름. 그 날 먹을 약이 없는 시점은 빠진다 */
export function scheduleOn(medications: MedicationDraft[], date: string) {
  return intakeSlots
    .map((slot) => ({
      slot,
      names: medications
        .filter((medication) => isTakingOn(medication, date) && slotsFor(medication.times).includes(slot))
        .map((medication) => medication.name),
    }))
    .filter((item) => item.names.length > 0)
}

/** 복약 체크 기록의 키 */
export const checkKey = (date: string, slot: string) => `${date}|${slot}`
