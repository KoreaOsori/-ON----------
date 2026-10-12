import type { HealthProfile } from "@/types/health"

export const disclaimer =
  "데이터에 등록된 정보 기준이며 복용 전 약사·의사와 상담하세요."

export const emptyProfile: HealthProfile = { gender: "", age: "", pregnant: "" }

export const GUEST_DAILY_QUESTION_LIMIT = 8

export const MAX_INTERACTION_DRUGS = 5

/** 성별 · 나이 · 임신 여부를 "여성 · 35세 · 임신 아님" 형태로 요약 */
export function summarizeProfile(profile: HealthProfile) {
  return [profile.gender, profile.age && `${profile.age}세`, profile.pregnant]
    .filter(Boolean)
    .join(" · ")
}
