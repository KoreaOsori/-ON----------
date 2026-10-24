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
  /** 마이페이지 인사말에 쓰는 이름 (서버 계정의 nickname = 이메일 앞부분) */
  displayName?: string
  /** 복약 체크 기록 (서버 intake_logs 에서 만든 값). "YYYY-MM-DD|약 이름|시간대" */
  intakeChecks?: string[]
}

export type RegisteredMedication = {
  /** 서버 복용약 id (저장 전에는 없음) */
  id?: string
  name: string
  /** 1회 복용량 (정) */
  amount: string
  /** 하루 횟수 */
  times: string
  /** 복용 일수 */
  days: string
  start: string
}
