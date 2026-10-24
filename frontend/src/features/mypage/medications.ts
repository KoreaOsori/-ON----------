import type { HealthProfile, RegisteredMedication } from "@/types/health"

// 내 복용약 = 건강정보에서 고른 약(medicines/medicineItems) + 약 등록·직접 추가로 저장한 약(registeredMedications).
// 같은 이름이면 하나로 보고, 복용 정보(1회 양·하루 횟수·일수·시작일)는 registeredMedications 에 둔다.

export type MyMedicine = {
  name: string
  info?: RegisteredMedication
  source: string
}

export const emptyMedication = (name = ""): RegisteredMedication => ({
  name,
  amount: "",
  times: "",
  days: "",
  start: today(),
})

/** 브라우저 기준 오늘 (YYYY-MM-DD) */
export function today() {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

export function myMedicines(profile: HealthProfile): MyMedicine[] {
  const registered = profile.registeredMedications ?? []
  const byName = new Map(registered.map((item) => [item.name, item]))
  const profileMedicines = profile.medicines ?? []
  return [
    ...profileMedicines.map((name) => ({ name, info: byName.get(name), source: "건강정보에서 등록" })),
    ...registered
      .filter((item) => !profileMedicines.includes(item.name))
      .map((item) => ({ name: item.name, info: item, source: "약 등록" })),
  ]
}

/** 복용 정보 한 줄: 1일 3회 · 1회 1정 · 7일분 (모르는 값은 빼고 표시) */
export const dosageText = (item: RegisteredMedication) =>
  [
    item.times && `1일 ${item.times}회`,
    item.amount && `1회 ${item.amount}정`,
    item.days && `${item.days}일분`,
    item.start && `${item.start} 시작`,
  ]
    .filter(Boolean)
    .join(" · ")

/** 시작일 + 일수가 지났으면 true (정보가 없으면 계속 복용 중으로 본다) */
export function isFinished(item: RegisteredMedication | undefined, on = today()) {
  if (!item?.start || !Number(item.days)) return false
  const end = new Date(item.start)
  end.setDate(end.getDate() + Number(item.days))
  return on >= end.toISOString().slice(0, 10)
}

/** 같은 이름의 복용 정보를 바꾸거나 새로 추가한다 */
export function saveMedication(profile: HealthProfile, item: RegisteredMedication): HealthProfile {
  const name = item.name.trim()
  const others = (profile.registeredMedications ?? []).filter((saved) => saved.name !== name)
  return { ...profile, registeredMedications: [...others, { ...item, name }] }
}

/** 건강정보에서 고른 약과 등록한 복용 정보에서 모두 뺀다 */
export function removeMedication(profile: HealthProfile, name: string): HealthProfile {
  const next = {
    ...profile,
    medicines: (profile.medicines ?? []).filter((item) => item !== name),
    medicineItems: (profile.medicineItems ?? []).filter((item) => item.name !== name),
    registeredMedications: (profile.registeredMedications ?? []).filter((item) => item.name !== name),
  }
  // 마지막 약까지 지우면 "약을 선택할게요" 상태가 남지 않게 비운다
  return myMedicines(next).length ? next : { ...next, medicineStatus: undefined }
}

const slotsByTimes: Record<number, string[]> = {
  1: ["아침 식후"],
  2: ["아침 식후", "저녁 식후"],
  3: ["아침 식후", "점심 식후", "저녁 식후"],
}

/** 체크리스트 정렬 순서 */
export const slotOrder = ["아침 식후", "점심 식후", "저녁 식후", "취침 전", "오늘 복용"]

/** 하루 횟수에 맞춘 복용 시간대. 4회 이상이면 취침 전을 더하고, 모르면 "오늘 복용" 한 칸 */
export function intakeSlotsOf(item: RegisteredMedication | undefined) {
  const times = Number(item?.times)
  if (!times) return ["오늘 복용"]
  return slotsByTimes[times] ?? [...slotsByTimes[3], "취침 전"]
}
