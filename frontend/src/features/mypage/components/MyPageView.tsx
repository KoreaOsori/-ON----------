"use client"

import { useState } from "react"
import { ChevronLeft } from "lucide-react"
import { emptyProfile } from "@/lib/constants"
import { drugs } from "@/mocks/drugs"
import { useSession } from "@/providers/SessionProvider"
import type { MedicationDraft, MyPageViewName, OcrStep } from "../types"
import AccountSettings from "./AccountSettings"
import ConsentForm from "./ConsentForm"
import HealthSetup from "./HealthSetup"
import LoginPanel from "./LoginPanel"
import MedicationCalendar from "./MedicationCalendar"
import MedicineRegistration from "./MedicineRegistration"
import MyPageHome from "./MyPageHome"
import NotificationSettings from "./NotificationSettings"

const initialDraft: MedicationDraft = {
  name: "가나다정",
  amount: "1",
  times: "3",
  days: "7",
  start: "2026-10-07",
}

const viewTitles: Partial<Record<MyPageViewName, string>> = {
  calendar: "복약 캘린더",
  notifications: "알림 설정",
  settings: "설정",
}

export default function MyPageView() {
  const { logged, setLogged, memberProfile: profile, setMemberProfile: setProfile } = useSession()
  const [view, setView] = useState<MyPageViewName>("home")
  const [email, setEmail] = useState("")
  const [consents, setConsents] = useState<boolean[]>([false, false, false])
  const [checked, setChecked] = useState<string[]>([])
  const [ocr, setOcr] = useState<OcrStep>(0)
  const [draft, setDraft] = useState<MedicationDraft>(initialDraft)
  const [saved, setSaved] = useState(false)

  const toggleCheck = (key: string) =>
    setChecked((previous) =>
      previous.includes(key) ? previous.filter((item) => item !== key) : [...previous, key],
    )

  const deleteData = () => {
    setChecked([])
    setSaved(false)
    setDraft(initialDraft)
    setConsents([false, false, false, false])
  }

  if (!logged && view === "home")
    return <LoginPanel email={email} setEmail={setEmail} onStart={() => setView("consent")} />

  if (view === "consent")
    return (
      <ConsentForm
        consents={consents}
        setConsents={setConsents}
        onContinue={() => setView("profile")}
      />
    )

  if (view === "profile")
    return (
      <HealthSetup
        profile={profile}
        medicines={drugs}
        onCancel={() => setView(logged ? "home" : "consent")}
        onSave={(value) => {
          setProfile(value)
          setLogged(true)
          setView("home")
        }}
      />
    )

  if (ocr)
    return (
      <MedicineRegistration
        step={ocr}
        setStep={setOcr}
        draft={draft}
        setDraft={setDraft}
        onSave={() => {
          setSaved(true)
          setOcr(4)
        }}
        onDone={() => {
          setOcr(0)
          setView("notifications")
        }}
      />
    )

  return (
    <div className="mx-auto max-w-[1120px]">
      {view !== "home" && (
        <button
          onClick={() => setView("home")}
          className="mb-5 flex min-h-11 items-center gap-2 text-sm text-slate-500"
        >
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
          savedMedication={saved ? draft : null}
          onNavigate={setView}
          onRegisterMedicine={() => setOcr(1)}
        />
      ) : view === "calendar" ? (
        <MedicationCalendar checked={checked} toggleCheck={toggleCheck} />
      ) : view === "notifications" ? (
        <NotificationSettings />
      ) : (
        <AccountSettings
          consents={consents}
          setConsents={setConsents}
          onEditProfile={() => setView("profile")}
          onLogout={() => {
            setLogged(false)
            setView("home")
          }}
          onDeleteData={deleteData}
          onWithdraw={() => {
            deleteData()
            setLogged(false)
            setProfile(emptyProfile)
            setView("home")
            setEmail("")
          }}
        />
      )}
    </div>
  )
}
