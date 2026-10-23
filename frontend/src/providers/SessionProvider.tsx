"use client"

import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { emptyProfile } from "@/lib/constants"
import type { RegisteredMedication } from "@/features/mypage/types"
import type { HealthProfile } from "@/types/health"

type SessionContextValue = {
  logged: boolean
  setLogged: (value: boolean) => void
  guestProfile: HealthProfile
  setGuestProfile: (value: HealthProfile) => void
  memberProfile: HealthProfile
  setMemberProfile: (value: HealthProfile) => void
  /** 약 등록으로 저장한 복용약·일정 */
  medications: RegisteredMedication[]
  setMedications: (value: RegisteredMedication[]) => void
  /** 복약 체크 기록 (checkKey: 날짜|복용 시점) */
  intakeChecks: string[]
  setIntakeChecks: (value: string[]) => void
  /** 로고 클릭 시 증가시켜 챗봇 화면을 초기화한다 */
  homeRevision: number
  resetHome: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

// 회원(데모) 로그인 상태와 건강정보·복용약·복약 기록은 이 브라우저에만 저장한다 (서버로 보내지 않음).
// 저장소를 쓸 수 없는 환경(사생활 보호 모드 등)에서는 저장 없이 화면 상태로만 동작한다.
const STORAGE_KEY = "yakon-member"

type SavedMember = {
  logged: boolean
  profile: HealthProfile
  medications?: RegisteredMedication[]
  intakeChecks?: string[]
}

function loadMember(): SavedMember | null {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

function saveMember(member: SavedMember) {
  try {
    if (member.logged) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(member))
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 저장하지 못해도 화면은 그대로 쓸 수 있다
  }
}

// 데모 단계의 로그인·건강정보 상태. 백엔드 인증(JWT) 연동 시 이 Provider에서 토큰/사용자 정보를 관리한다.
export default function SessionProvider({ children }: { children: ReactNode }) {
  const [logged, setLogged] = useState(false)
  const [guestProfile, setGuestProfile] = useState<HealthProfile>(emptyProfile)
  const [memberProfile, setMemberProfile] = useState<HealthProfile>(emptyProfile)
  const [medications, setMedications] = useState<RegisteredMedication[]>([])
  const [intakeChecks, setIntakeChecks] = useState<string[]>([])
  const [homeRevision, setHomeRevision] = useState(0)
  const [restored, setRestored] = useState(false)

  // 서버 렌더링에는 저장소가 없으므로 화면이 뜬 뒤에 불러온다.
  // 처음부터 저장값으로 그리면 서버 화면과 달라져 hydration 오류가 나므로, 의도적으로 effect 에서 한 번 바꾼다
  useEffect(() => {
    const saved = loadMember()
    if (saved) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLogged(saved.logged)
      setMemberProfile(saved.profile)
      setMedications(saved.medications ?? [])
      setIntakeChecks(saved.intakeChecks ?? [])
    }
    setRestored(true)
  }, [])

  useEffect(() => {
    if (restored) saveMember({ logged, profile: memberProfile, medications, intakeChecks })
  }, [restored, logged, memberProfile, medications, intakeChecks])

  return (
    <SessionContext.Provider
      value={{
        logged,
        setLogged,
        guestProfile,
        setGuestProfile,
        memberProfile,
        setMemberProfile,
        medications,
        setMedications,
        intakeChecks,
        setIntakeChecks,
        homeRevision,
        resetHome: () => setHomeRevision((previous) => previous + 1),
      }}
    >
      {children}
    </SessionContext.Provider>
  )
}

export function useSession() {
  const context = useContext(SessionContext)
  if (!context) throw new Error("useSession은 SessionProvider 안에서 사용해야 합니다.")
  return context
}
