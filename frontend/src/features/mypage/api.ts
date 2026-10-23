import { apiFetch } from "@/lib/api/client"

export type OAuthProvider = "kakao" | "naver" | "google"

export type TokenResponse = {
  accessToken: string
  refreshToken: string
  tokenType: "bearer"
  expiresIn: number
}

export type HealthProfilePayload = {
  birth: string
  gender: string
  height: number
  weight: number
  pregnant: string
  medicineStatus: string
  medicines: string[]
  conditions: string
}

export type Medication = {
  id: string
  name: string
  amount: number
  timesPerDay: number
  days: number
  startDate: string
}

// 인증
export const getOAuthAuthorizeUrl = (provider: OAuthProvider) =>
  apiFetch<{ authorizeUrl: string }>(`/auth/oauth/${provider}/authorize`)

export const refreshToken = (refreshToken: string) =>
  apiFetch<TokenResponse>("/auth/refresh", { method: "POST", body: { refreshToken } })

// 회원 / 건강정보
export const getMe = () => apiFetch<{ id: string; email: string | null }>("/users/me")

export const saveConsents = (consents: Record<string, boolean>) =>
  apiFetch<void>("/users/me/consents", { method: "PUT", body: { consents } })

export const saveHealthProfile = (profile: HealthProfilePayload) =>
  apiFetch<HealthProfilePayload>("/users/me/health-profile", { method: "PUT", body: profile })

export const deleteAccount = () => apiFetch<void>("/users/me", { method: "DELETE" })

// 복용약 / 복약 기록
export const listMedications = () => apiFetch<Medication[]>("/medications")

export const createMedication = (payload: Omit<Medication, "id">) =>
  apiFetch<Medication>("/medications", { method: "POST", body: payload })

export const logIntake = (medicationId: string, payload: { date: string; slot: string; taken: boolean }) =>
  apiFetch<void>(`/medications/${medicationId}/logs`, { method: "PUT", body: payload })

// 처방전 업로드 → OCR: 알약·처방전 공용 함수는 features/photo/api.ts (uploadPhoto · recognizePrescription)
export { recognizePrescription, uploadPhoto } from "@/features/photo/api"
