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
  conditions?: string
}
