import { apiFetch } from "@/lib/api/client"
import type { MedicineSummary } from "@/features/medicine/api"

export type TokenResponse = {
  accessToken: string
  refreshToken: string
  tokenType: "bearer"
  expiresIn: number
}

export type Me = { id: string; email: string | null; nickname: string | null }

export type ConsentType = "terms" | "privacy" | "health" | "marketing"

export type HealthProfilePayload = {
  birth: string
  gender: string
  height: number
  weight: number
  pregnant: string
  medicineStatus: string
  medicines: string[]
  medicineItems: MedicineSummary[]
  conditions: string
}

export type Medication = {
  id: string
  name: string
  amount: number | null
  timesPerDay: number | null
  days: number | null
  startDate: string | null
}

export type MedicationInput = Omit<Medication, "id">

export type IntakeLog = { medicationId: string; date: string; slot: string; taken: boolean }

// 인증: 이메일(아이디)만으로 로그인 (없으면 가입). 비밀번호·메일 인증·소셜 로그인 없음
export const login = (email: string) =>
  apiFetch<TokenResponse>("/auth/login", { method: "POST", body: { email } })

// 재발급 요청 자체는 401 재시도를 하지 않는다 (retried = true)
export const refreshToken = (refreshToken: string) =>
  apiFetch<TokenResponse>("/auth/refresh", { method: "POST", body: { refreshToken } }, true)

// 회원 / 동의 / 건강정보
export const getMe = () => apiFetch<Me>("/users/me")

export const getConsents = () => apiFetch<Partial<Record<ConsentType, boolean>>>("/users/me/consents")

export const saveConsents = (consents: Partial<Record<ConsentType, boolean>>) =>
  apiFetch<void>("/users/me/consents", { method: "PUT", body: { consents } })

export const getHealthProfile = () => apiFetch<HealthProfilePayload | null>("/users/me/health-profile")

export const saveHealthProfile = (profile: HealthProfilePayload) =>
  apiFetch<HealthProfilePayload>("/users/me/health-profile", { method: "PUT", body: profile })

export const deleteAccount = () => apiFetch<void>("/users/me", { method: "DELETE" })

// 복용약 / 복약 기록
export const listMedications = () => apiFetch<Medication[]>("/medications")

export const createMedication = (payload: MedicationInput) =>
  apiFetch<Medication>("/medications", { method: "POST", body: payload })

export const updateMedication = (id: string, payload: Omit<MedicationInput, "name">) =>
  apiFetch<Medication>(`/medications/${id}`, { method: "PATCH", body: payload })

export const deleteMedication = (id: string) => apiFetch<void>(`/medications/${id}`, { method: "DELETE" })

export const deleteAllMedications = () => apiFetch<void>("/medications", { method: "DELETE" })

/** month: YYYY-MM */
export const listIntakeLogs = (month: string) => apiFetch<IntakeLog[]>("/medications/logs", { query: { month } })

export const logIntake = (medicationId: string, payload: { date: string; slot: string; taken: boolean }) =>
  apiFetch<void>(`/medications/${medicationId}/logs`, { method: "PUT", body: payload })

// 처방전 업로드 → OCR: 알약·처방전 공용 함수는 features/photo/api.ts (uploadPhoto · recognizePrescription)
export { recognizePrescription, uploadPhoto } from "@/features/photo/api"
