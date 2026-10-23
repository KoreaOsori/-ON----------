import type { HealthProfile } from "@/types/health"
import type { DurCaution } from "./api"

/** 만 나이(년)·개월·주. 생년월일이 있으면 그것으로, 없으면 입력한 나이로 계산한다. 알 수 없으면 null */
function ageOf(profile: HealthProfile) {
  if (profile.birth) {
    const birth = new Date(`${profile.birth}T00:00:00`)
    const today = new Date()
    if (Number.isNaN(birth.getTime())) return null
    let months = (today.getFullYear() - birth.getFullYear()) * 12 + today.getMonth() - birth.getMonth()
    if (today.getDate() < birth.getDate()) months -= 1
    const weeks = Math.floor((today.getTime() - birth.getTime()) / (7 * 24 * 60 * 60 * 1000))
    return { 세: Math.floor(months / 12), 개월: months, 주: weeks }
  }
  const years = Number.parseInt(profile.age, 10)
  return Number.isNaN(years) ? null : { 세: years, 개월: years * 12, 주: years * 52 }
}

/**
 * 이 DUR 주의가 사용자 건강정보에 해당하는지. 판단할 수 없으면 null (프로필 없음, 프로필과 무관한 주의 등).
 * - 임부금기: 임신 여부가 "임신 중"이면 해당, "확인 필요"면 null
 * - 특정연령대금기: "12세 미만", "24개월 이하", "4주 미만", "65세 이상" 형식의 기준과 나이를 비교
 * - 노인주의: 만 65세 이상이면 해당
 */
export function matchesProfile(caution: DurCaution, profile: HealthProfile): boolean | null {
  if (caution.type === "임부금기") {
    if (profile.pregnant === "임신 중") return true
    return profile.pregnant === "임신 아님" ? false : null
  }
  const age = ageOf(profile)
  if (!age) return null
  if (caution.type === "노인주의") return age.세 >= 65
  if (caution.type === "특정연령대금기") {
    const rule = caution.ageBase?.match(/^(\d+)\s*(세|개월|주)\s*(미만|이하|이상)$/)
    if (!rule) return null
    const [, limit, unit, kind] = rule
    const value = age[unit as keyof typeof age]
    const n = Number(limit)
    return kind === "미만" ? value < n : kind === "이하" ? value <= n : value >= n
  }
  return null
}
