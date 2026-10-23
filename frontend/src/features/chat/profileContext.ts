import { summarizeProfile } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"

/** v3 API 의 profile_context 최대 길이 */
export const MAX_PROFILE_CONTEXT = 1000

/** 복용 중인 약 이름 (마이페이지: 약 검색에서 고른 약, 임시 정보: 직접 입력) */
export function medicinesOf(profile: HealthProfile): string[] {
  const names = profile.medicines?.length
    ? profile.medicines
    : (profile.medicineItems ?? []).map((item) => item.name)
  return [...new Set(names.map((name) => name.trim()).filter(Boolean))]
}

/**
 * 성별·나이·임신 여부·복용 중인 약을 v3 의 profile_context 문자열로 만든다. 값이 하나도 없으면 undefined.
 * 예) "성별: 여성\n나이: 만 35세\n임신 여부: 임신 중\n복용 중인 약: 와파린정, 아스피린장용정100밀리그램"
 */
export function buildProfileContext(profile: HealthProfile): string | undefined {
  const medicines = medicinesOf(profile)
  const lines = [
    profile.gender && `성별: ${profile.gender}`,
    profile.age && `나이: 만 ${profile.age}세`,
    profile.pregnant && `임신 여부: ${profile.pregnant}`,
    medicines.length > 0 && `복용 중인 약: ${medicines.join(", ")}`,
  ].filter(Boolean)
  const text = lines.join("\n")
  return text ? text.slice(0, MAX_PROFILE_CONTEXT) : undefined
}

/** 화면 표시용 요약: "여성 · 35세 · 임신 중 · 복용약 2개" */
export function summarizeForChat(profile: HealthProfile): string {
  const medicines = medicinesOf(profile)
  return [summarizeProfile(profile), medicines.length > 0 && `복용약 ${medicines.length}개`]
    .filter(Boolean)
    .join(" · ")
}
