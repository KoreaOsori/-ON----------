"use client"

import { useRef, useState } from "react"
import { ChevronLeft, LoaderCircle } from "lucide-react"
import { useSession } from "@/providers/SessionProvider"
import type { HealthProfile } from "@/types/health"
import { deleteAccount, getConsents, saveConsents } from "../api"
import { today } from "../medications"
import {
  clearMedicationData,
  loadMonth,
  removeMedicationByName,
  saveHealth,
  toggleIntake,
  upsertMedication,
} from "../sync"
import type { MedicationDraft, MyPageViewName, OcrStep } from "../types"
import AccountSettings from "./AccountSettings"
import ConsentForm from "./ConsentForm"
import HealthSetup from "./HealthSetup"
import LoginPanel from "./LoginPanel"
import MedicationCalendar from "./MedicationCalendar"
import MedicationManager from "./MedicationManager"
import MedicineRegistration from "./MedicineRegistration"
import MyPageHome from "./MyPageHome"

const emptyDraft = (): MedicationDraft => ({ name: "", amount: "", times: "", days: "", start: today() })

const viewTitles: Partial<Record<MyPageViewName, string>> = {
  calendar: "복약 캘린더",
  settings: "설정",
}

// 동의 화면·설정의 체크 순서
const consentTypes = ["terms", "privacy", "health", "marketing"] as const

export default function MyPageView() {
  const { logged, setLogged, restoring, signIn, signOut, memberProfile: profile, setMemberProfile: setProfile } =
    useSession()
  const [view, setView] = useState<MyPageViewName>("home")
  const [consents, setConsents] = useState<boolean[]>([false, false, false, false])
  const [ocr, setOcr] = useState<OcrStep>(0)
  const [draft, setDraft] = useState<MedicationDraft>(emptyDraft)
  const [managing, setManaging] = useState(false)
  const [error, setError] = useState("")
  // 서버 저장이 끝나기 전에 또 누르면 오래된 화면 값으로 덮어쓰므로 한 번에 하나씩
  const busy = useRef(false)

  /** 서버에 저장하고 돌려받은 값으로 화면을 바꾼다. 실패하면 화면은 그대로 두고 안내 */
  const save = async (action: () => Promise<HealthProfile>) => {
    if (busy.current) return false
    busy.current = true
    setError("")
    try {
      setProfile(await action())
      return true
    } catch {
      setError("저장하지 못했어요. 잠시 후 다시 시도해 주세요.")
      return false
    } finally {
      busy.current = false
    }
  }

  const banner = error && (
    <p role="alert" className="mx-auto mb-5 max-w-[1120px] rounded-xl bg-red-50 p-4 text-sm text-red-700">
      {error}
    </p>
  )

  // 약 등록은 매번 빈 칸에서 시작한다
  const startRegistration = () => {
    setDraft(emptyDraft())
    setOcr(1)
  }

  const checked = profile.intakeChecks ?? []
  const toggleCheck = (key: string) => save(() => toggleIntake(profile, key))

  const openSettings = () => {
    setView("settings")
    getConsents()
      .then((saved) => setConsents(consentTypes.map((type) => saved[type] ?? false)))
      .catch(() => undefined) // 못 불러와도 필수 동의는 이미 한 상태
  }

  const goHome = () => {
    setView("home")
    setOcr(0)
    setManaging(false)
  }

  if (restoring)
    return (
      <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-slate-500">
        <LoaderCircle className="animate-spin" />내 정보를 불러오는 중이에요
      </div>
    )

  if (!logged && view === "home")
    return (
      <LoginPanel
        onSubmit={async (email) => {
          // 건강정보까지 입력한 계정이면 바로 마이페이지, 처음이면 동의 → 건강정보 입력
          if (!(await signIn(email))) setView("consent")
        }}
      />
    )

  if (view === "consent")
    return (
      <ConsentForm consents={consents} setConsents={setConsents} onContinue={() => setView("profile")} />
    )

  if (view === "profile")
    return (
      <>
        {banner}
        <HealthSetup
          profile={profile}
          onCancel={() => setView(logged ? "home" : "consent")}
          onSave={async (value) => {
            // 처음 입력할 때만 동의를 함께 저장 (건강정보 저장에는 필수 동의가 필요)
            const agreed = logged
              ? undefined
              : Object.fromEntries(consentTypes.map((type, index) => [type, consents[index] ?? false]))
            if (await save(() => saveHealth(profile, value, agreed))) {
              setLogged(true)
              setView("home")
            }
          }}
        />
      </>
    )

  if (ocr)
    return (
      <>
        {banner}
        <MedicineRegistration
          step={ocr}
          setStep={setOcr}
          draft={draft}
          setDraft={setDraft}
          onSave={async () => {
            if (await save(() => upsertMedication(profile, draft))) setOcr(4)
          }}
          onDone={goHome}
        />
      </>
    )

  return (
    <div className="mx-auto max-w-[1120px]">
      {banner}
      {view !== "home" && (
        <button onClick={goHome} className="mb-5 flex min-h-11 items-center gap-2 text-sm text-slate-500">
          <ChevronLeft size={18} />
          마이페이지
        </button>
      )}
      <h1 className="mb-7 text-3xl font-bold">{viewTitles[view] ?? "마이페이지"}</h1>
      {view === "home" ? (
        <MyPageHome
          profile={profile}
          checked={checked}
          toggleCheck={toggleCheck}
          onNavigate={(next) => (next === "settings" ? openSettings() : setView(next))}
          onRegisterMedicine={startRegistration}
          onManageMedicines={() => setManaging(true)}
        />
      ) : view === "calendar" ? (
        <MedicationCalendar
          profile={profile}
          checked={checked}
          toggleCheck={toggleCheck}
          onMonthChange={(month) =>
            loadMonth(month, profile)
              .then((checks) => {
                if (checks)
                  setProfile((previous) => ({
                    ...previous,
                    intakeChecks: [...new Set([...(previous.intakeChecks ?? []), ...checks])],
                  }))
              })
              .catch(() => setError("복약 기록을 불러오지 못했어요."))
          }
        />
      ) : (
        <AccountSettings
          consents={consents}
          setConsents={(values) => {
            setConsents(values)
            saveConsents({ marketing: values[3] ?? false }).catch(() => setError("동의 설정을 저장하지 못했어요."))
          }}
          onEditProfile={() => setView("profile")}
          onLogout={() => {
            signOut()
            goHome()
          }}
          onDeleteData={() => save(() => clearMedicationData(profile))}
          onWithdraw={async () => {
            try {
              await deleteAccount() // 서버에서 회원·건강정보·복용약·복약 기록 모두 삭제
              signOut()
              goHome()
            } catch {
              setError("탈퇴하지 못했어요. 잠시 후 다시 시도해 주세요.")
            }
          }}
        />
      )}
      {managing && (
        <MedicationManager
          profile={profile}
          onSave={(item) => save(() => upsertMedication(profile, item))}
          onRemove={(name) => save(() => removeMedicationByName(profile, name))}
          onClose={() => setManaging(false)}
          onRegisterByPhoto={() => {
            setManaging(false)
            startRegistration()
          }}
        />
      )}
    </div>
  )
}
