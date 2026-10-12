"use client"

import { createContext, useContext, useState, type ReactNode } from "react"
import { emptyProfile } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"

type SessionContextValue = {
  logged: boolean
  setLogged: (value: boolean) => void
  guestProfile: HealthProfile
  setGuestProfile: (value: HealthProfile) => void
  memberProfile: HealthProfile
  setMemberProfile: (value: HealthProfile) => void
  /** 로고 클릭 시 증가시켜 챗봇 화면을 초기화한다 */
  homeRevision: number
  resetHome: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

// 데모 단계의 로그인·건강정보 상태. 백엔드 인증(JWT) 연동 시 이 Provider에서 토큰/사용자 정보를 관리한다.
export default function SessionProvider({ children }: { children: ReactNode }) {
  const [logged, setLogged] = useState(false)
  const [guestProfile, setGuestProfile] = useState<HealthProfile>(emptyProfile)
  const [memberProfile, setMemberProfile] = useState<HealthProfile>(emptyProfile)
  const [homeRevision, setHomeRevision] = useState(0)

  return (
    <SessionContext.Provider
      value={{
        logged,
        setLogged,
        guestProfile,
        setGuestProfile,
        memberProfile,
        setMemberProfile,
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
