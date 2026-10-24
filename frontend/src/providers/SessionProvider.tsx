"use client"

import { createContext, useContext, useEffect, useState, type Dispatch, type ReactNode, type SetStateAction } from "react"
import { login, refreshToken, type TokenResponse } from "@/features/mypage/api"
import { loadMember } from "@/features/mypage/sync"
import { setAccessToken, setTokenRefresher } from "@/lib/api/client"
import { emptyProfile } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"

type SessionContextValue = {
  /** 건강정보까지 입력한 회원으로 로그인했는지 */
  logged: boolean
  setLogged: (value: boolean) => void
  /** 새로고침 직후 서버에서 회원 정보를 불러오는 중 */
  restoring: boolean
  /** 이메일(아이디)로 로그인하고 서버의 내 정보를 불러온다. 건강정보가 있으면 true */
  signIn: (email: string) => Promise<boolean>
  signOut: () => void
  guestProfile: HealthProfile
  setGuestProfile: (value: HealthProfile) => void
  memberProfile: HealthProfile
  setMemberProfile: Dispatch<SetStateAction<HealthProfile>>
  /** 로고 클릭 시 증가시켜 챗봇 화면을 초기화한다 */
  homeRevision: number
  resetHome: () => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

// 회원 정보(건강정보·복용약·복약 기록)는 서버에 저장하고, 이 브라우저에는 로그인 토큰만 둔다.
// 저장소를 쓸 수 없는 환경(사생활 보호 모드 등)에서는 새로고침하면 다시 로그인해야 한다.
const STORAGE_KEY = "yakon-auth"
const LEGACY_KEY = "yakon-member" // 이전 버전: 건강정보를 브라우저에 저장하던 값

type StoredTokens = Pick<TokenResponse, "accessToken" | "refreshToken">

function loadTokens(): StoredTokens | null {
  try {
    window.localStorage.removeItem(LEGACY_KEY)
    const saved = window.localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

function saveTokens(tokens: StoredTokens | null) {
  try {
    if (tokens) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens))
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 저장하지 못해도 이번 화면에서는 계속 쓸 수 있다
  }
}

let tokens: StoredTokens | null = null
let refreshing: Promise<boolean> | null = null

function applyTokens(next: StoredTokens | null) {
  tokens = next
  setAccessToken(next?.accessToken ?? null)
  saveTokens(next)
}

// 액세스 토큰(30분)이 만료되면 리프레시 토큰(14일)으로 한 번 재발급한다. 동시에 여러 요청이 401 이어도 한 번만
function refreshTokens(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      if (!tokens) return false
      const issued = await refreshToken(tokens.refreshToken)
      applyTokens(issued)
      return true
    } catch {
      applyTokens(null)
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

export default function SessionProvider({ children }: { children: ReactNode }) {
  const [logged, setLogged] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const [guestProfile, setGuestProfile] = useState<HealthProfile>(emptyProfile)
  const [memberProfile, setMemberProfile] = useState<HealthProfile>(emptyProfile)
  const [homeRevision, setHomeRevision] = useState(0)

  // 서버 렌더링에는 저장소가 없으므로 화면이 뜬 뒤에 토큰을 읽고 서버에서 내 정보를 불러온다
  useEffect(() => {
    setTokenRefresher(refreshTokens)
    const saved = loadTokens()
    if (!saved) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setRestoring(false)
      return
    }
    applyTokens(saved)
    loadMember()
      .then(({ profile, hasProfile }) => {
        setMemberProfile(profile)
        setLogged(hasProfile)
      })
      .catch(() => applyTokens(null)) // 토큰이 만료됐거나 서버에 계정이 없으면 다시 로그인
      .finally(() => setRestoring(false))
  }, [])

  const signIn = async (email: string) => {
    applyTokens(await login(email))
    const { profile, hasProfile } = await loadMember()
    setMemberProfile(profile)
    setLogged(hasProfile)
    return hasProfile
  }

  const signOut = () => {
    applyTokens(null)
    setLogged(false)
    setMemberProfile(emptyProfile)
  }

  return (
    <SessionContext.Provider
      value={{
        logged,
        setLogged,
        restoring,
        signIn,
        signOut,
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
