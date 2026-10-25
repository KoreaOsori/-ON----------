import type { HealthProfile, RegisteredMedication } from "@/types/health"
import {
  createMedication,
  deleteAllMedications,
  deleteMedication,
  getHealthProfile,
  getMe,
  listIntakeLogs,
  listMedications,
  logIntake,
  saveConsents,
  saveHealthProfile,
  updateMedication,
  type ConsentType,
  type HealthProfilePayload,
  type Medication,
  type MedicationInput,
} from "./api"
import { addDays, removeMedication, saveMedication, today } from "./medications"

// 서버(회원·건강정보·복용약·복약 기록) ↔ 화면 상태(HealthProfile) 변환과 저장.
// 화면은 HealthProfile 하나만 보고, 바꿀 때는 서버에 먼저 저장한 뒤 돌려받은 값으로 상태를 바꾼다.

const NO_MEDICINE = "복용 중인 약 없음"

const ageOf = (birth: string) => {
  const day = new Date(`${birth}T00:00:00`)
  const now = new Date()
  const before = now.getMonth() < day.getMonth() || (now.getMonth() === day.getMonth() && now.getDate() < day.getDate())
  return String(now.getFullYear() - day.getFullYear() - (before ? 1 : 0))
}

const text = (value: number | null) => (value == null ? "" : String(value))
const numberOrNull = (value: string) => (Number(value) >= 1 ? Math.floor(Number(value)) : null)

export const toRegistered = (medication: Medication): RegisteredMedication => ({
  id: medication.id,
  name: medication.name,
  itemSeq: medication.itemSeq ?? undefined,
  amount: text(medication.amount),
  times: text(medication.timesPerDay),
  days: text(medication.days),
  start: medication.startDate ?? "",
})

const toInput = (item: RegisteredMedication): MedicationInput => ({
  name: item.name.trim(),
  itemSeq: item.itemSeq ?? null,
  amount: numberOrNull(item.amount),
  timesPerDay: numberOrNull(item.times),
  days: numberOrNull(item.days),
  startDate: item.start || null,
})

const toPayload = (profile: HealthProfile): HealthProfilePayload => ({
  birth: profile.birth ?? "",
  gender: profile.gender,
  height: Number(profile.height),
  weight: Number(profile.weight),
  pregnant: profile.pregnant,
  medicineStatus: profile.medicineStatus || NO_MEDICINE,
  medicines: profile.medicines ?? [],
  medicineItems: profile.medicineItems ?? [],
  conditions: profile.conditions ?? "",
})

const monthOf = (date: string) => date.slice(0, 7)

// 이미 불러온 달 (캘린더에서 달을 넘길 때 한 번만 부른다). 로그인할 때마다 비운다
const loadedMonths = new Set<string>()

const checksOf = (logs: { medicationId: string; date: string; slot: string; taken: boolean }[], medicines: RegisteredMedication[]) => {
  const names = new Map(medicines.map((item) => [item.id, item.name]))
  return logs
    .filter((log) => log.taken && names.has(log.medicationId))
    .map((log) => `${log.date}|${names.get(log.medicationId)}|${log.slot}`)
}

/** 로그인 직후·새로고침 때 서버에서 내 정보를 모두 불러온다. hasProfile = 건강정보까지 입력한 계정 */
export async function loadMember(): Promise<{ profile: HealthProfile; hasProfile: boolean }> {
  loadedMonths.clear()
  const [me, health, medications] = await Promise.all([getMe(), getHealthProfile(), listMedications()])
  const registeredMedications = medications.map(toRegistered)
  // 오늘 체크리스트와 지난달 말 기록까지 보이도록 이번 달·지난달
  const thisMonth = monthOf(today())
  const lastMonth = monthOf(addDays(`${thisMonth}-01`, -1))
  const logs = (await Promise.all([thisMonth, lastMonth].map(listIntakeLogs))).flat()
  loadedMonths.add(thisMonth).add(lastMonth)
  const profile: HealthProfile = {
    gender: health?.gender ?? "",
    age: health ? ageOf(health.birth) : "",
    pregnant: health?.pregnant ?? "",
    birth: health?.birth,
    height: health ? String(health.height) : undefined,
    weight: health ? String(health.weight) : undefined,
    medicineStatus: health?.medicineStatus,
    medicines: health?.medicines ?? [],
    medicineItems: health?.medicineItems ?? [],
    conditions: health?.conditions,
    displayName: me.nickname ?? undefined,
    registeredMedications,
    intakeChecks: checksOf(logs, registeredMedications),
  }
  return { profile, hasProfile: !!health }
}

/** 캘린더에서 아직 안 불러온 달의 복약 기록 (이미 불러온 달이면 null) */
export async function loadMonth(month: string, profile: HealthProfile): Promise<string[] | null> {
  if (loadedMonths.has(month)) return null
  loadedMonths.add(month)
  try {
    return checksOf(await listIntakeLogs(month), profile.registeredMedications ?? [])
  } catch (error) {
    loadedMonths.delete(month) // 다음에 다시 시도
    throw error
  }
}

/**
 * 건강정보 저장. 처음이면 동의도 저장한다.
 * 건강정보에서 고른 약은 복용약(medications)으로도 만들어, 복용 정보 입력과 복약 체크를 할 수 있게 한다.
 */
export async function saveHealth(
  previous: HealthProfile,
  next: HealthProfile,
  consents?: Partial<Record<ConsentType, boolean>>,
): Promise<HealthProfile> {
  if (consents) await saveConsents(consents)
  await saveHealthProfile(toPayload(next))
  let medications = previous.registeredMedications ?? []
  const picked = next.medicines ?? []
  // 건강정보에서 뺀 약은 복용약에서도 지운다
  for (const name of (previous.medicines ?? []).filter((item) => !picked.includes(item))) {
    const saved = medications.find((item) => item.name === name)
    if (saved?.id) await deleteMedication(saved.id)
    medications = medications.filter((item) => item.name !== name)
  }
  for (const name of picked.filter((item) => !medications.some((saved) => saved.name === item))) {
    const created = await createMedication({
      name,
      itemSeq: null,
      amount: null,
      timesPerDay: null,
      days: null,
      startDate: null,
    })
    medications = [...medications, toRegistered(created)]
  }
  return { ...next, age: next.birth ? ageOf(next.birth) : next.age, registeredMedications: medications }
}

/** 복용약 추가 또는 복용 정보 수정 (같은 이름이면 수정) */
export async function upsertMedication(profile: HealthProfile, item: RegisteredMedication): Promise<HealthProfile> {
  const name = item.name.trim()
  const saved = (profile.registeredMedications ?? []).find((medication) => medication.name === name)
  const { itemSeq, amount, timesPerDay, days, startDate } = toInput({ ...item, name })
  const dosage = { amount, timesPerDay, days, startDate }
  // 품목기준코드는 이름처럼 처음 등록할 때만 저장한다
  const result = saved?.id
    ? await updateMedication(saved.id, dosage)
    : await createMedication({ name, itemSeq, ...dosage })
  return saveMedication(profile, toRegistered(result))
}

/** 복용약 삭제. 건강정보에서 고른 약이면 건강정보의 약 목록에서도 뺀다 */
export async function removeMedicationByName(profile: HealthProfile, name: string): Promise<HealthProfile> {
  const saved = (profile.registeredMedications ?? []).find((medication) => medication.name === name)
  if (saved?.id) await deleteMedication(saved.id)
  const next = removeMedication(profile, name)
  if ((profile.medicines ?? []).includes(name) || next.medicineStatus !== profile.medicineStatus)
    await saveHealthProfile(toPayload(next))
  return next
}

/** 복약 체크 켜기/끄기. key = "YYYY-MM-DD|약 이름|시간대" */
export async function toggleIntake(profile: HealthProfile, key: string): Promise<HealthProfile> {
  const [date, name, slot] = key.split("|")
  const checks = profile.intakeChecks ?? []
  const taken = !checks.includes(key)
  let next = profile
  let medication = (profile.registeredMedications ?? []).find((item) => item.name === name)
  if (!medication?.id) {
    // 서버에 아직 없는 약 (이전 버전에서 브라우저에만 저장된 약 등) → 먼저 복용약으로 만든다
    next = await upsertMedication(profile, medication ?? { name, amount: "", times: "", days: "", start: "" })
    medication = next.registeredMedications?.find((item) => item.name === name)
  }
  await logIntake(medication!.id!, { date, slot, taken })
  return { ...next, intakeChecks: taken ? [...checks, key] : checks.filter((item) => item !== key) }
}

/** 설정 > 데이터 삭제: 복용약·복약 기록을 지우고 건강정보의 약 목록도 비운다 (기본정보·지병은 남김) */
export async function clearMedicationData(profile: HealthProfile): Promise<HealthProfile> {
  await deleteAllMedications()
  const next: HealthProfile = {
    ...profile,
    medicines: [],
    medicineItems: [],
    medicineStatus: NO_MEDICINE,
    registeredMedications: [],
    intakeChecks: [],
  }
  if (profile.birth) await saveHealthProfile(toPayload(next))
  return next
}
