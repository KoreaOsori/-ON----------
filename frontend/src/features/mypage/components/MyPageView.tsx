"use client"

import { useState } from "react"
import { ChevronLeft } from "lucide-react"
import { emptyProfile } from "@/lib/constants"
import { useSession } from "@/providers/SessionProvider"
import { toDateString, type MedicationDraft, type MyPageViewName, type OcrStep } from "../types"
import AccountSettings from "./AccountSettings"
import ConsentForm from "./ConsentForm"
import HealthSetup from "./HealthSetup"
import LoginPanel from "./LoginPanel"
import MedicationCalendar from "./MedicationCalendar"
import MedicineRegistration from "./MedicineRegistration"
import MyPageHome from "./MyPageHome"
import NotificationSettings from "./NotificationSettings"

// 약 등록의 인식 결과 예시 (사진 인식은 체험용). 약 이름은 검색해서 고르고, 시작일은 오늘
const newDraft = (): MedicationDraft => ({
  name: "",
  amount: "1",
  times: "3",
  days: "7",
  start: toDateString(new Date()),
  medicine: null,
})

const viewTitles: Partial<Record<MyPageViewName, string>> = {
  calendar: "복약 캘린더",
  notifications: "알림 설정",
  settings: "설정",
}

export default function MyPageView() {
  const {
    logged,
    setLogged,
    memberProfile: profile,
    setMemberProfile: setProfile,
    medications,
    setMedications,
    intakeChecks: checked,
    setIntakeChecks: setChecked,
  } = useSession()
  const [view, setView] = useState<MyPageViewName>("home")
  const [email, setEmail] = useState("")
  const [consents, setConsents] = useState<boolean[]>([false, false, false])
  const [ocr, setOcr] = useState<OcrStep>(0)
  const [draft, setDraft] = useState<MedicationDraft>(newDraft)

  const toggleCheck = (key: string) =>
    setChecked(checked.includes(key) ? checked.filter((item) => item !== key) : [...checked, key])

  // 복용약(건강정보에서 고른 약·약 등록으로 넣은 약)과 복약 체크 기록만 지운다. 기본정보·지병은 남긴다
  const deleteData = () => {
    setProfile({ ...profile, medicines: [], medicineItems: [], medicineStatus: undefined })
    setMedications([])
    setChecked([])
    setDraft(newDraft())
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
          // crypto.randomUUID 는 HTTPS 에서만 있어 (운영 웹은 HTTP) 시각 + 난수로 만든다
          setMedications([...medications, { ...draft, id: `${Date.now()}-${Math.random().toString(36).slice(2)}` }])
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
          medications={medications}
          onNavigate={setView}
          onRegisterMedicine={() => {
            setDraft(newDraft())
            setOcr(1)
          }}
        />
      ) : view === "calendar" ? (
        <MedicationCalendar checked={checked} toggleCheck={toggleCheck} medications={medications} />
      ) : view === "notifications" ? (
        <NotificationSettings />
      ) : (
        <AccountSettings
          consents={consents}
          setConsents={setConsents}
          onEditProfile={() => setView("profile")}
          onLogout={() => {
            // 서버 계정이 없어 브라우저에 저장한 건강정보·복용약이 곧 계정 데이터다. 같은 브라우저의 다음 사람에게 보이지 않게 지운다
            setLogged(false)
            setProfile(emptyProfile)
            setMedications([])
            setChecked([])
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
