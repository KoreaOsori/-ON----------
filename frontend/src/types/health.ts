import type { MedicineSummary } from "@/features/medicine/api"

export type HealthProfile = {
  gender: string
  age: string
  pregnant: string
  birth?: string
  height?: string
  weight?: string
  medicines?: string[]
  /** 복용약 (약 검색에서 고른 실제 약, id = 품목기준코드). medicines 는 이 약들의 이름 */
  medicineItems?: MedicineSummary[]
  medicineStatus?: string
  /** 약 등록(처방전·약봉투 인식 → 확인)으로 저장한 복용약과 복용 정보 */
  registeredMedications?: RegisteredMedication[]
  conditions?: string
}

export type RegisteredMedication = {
  name: string
  /** 1회 복용량 (정) */
  amount: string
  /** 하루 횟수 */
  times: string
  /** 복용 일수 */
  days: string
  start: string
}
