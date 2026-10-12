import { Bell, CalendarDays, Camera, ChevronRight, Pill, Settings, UserRound } from "lucide-react"
import type { HealthProfile } from "@/types/health"
import { intakeSlots, type MedicationDraft, type MyPageViewName } from "../types"

export default function MyPageHome({
  profile,
  checked,
  toggleCheck,
  savedMedication,
  onNavigate,
  onRegisterMedicine,
}: {
  profile: HealthProfile
  checked: string[]
  toggleCheck: (key: string) => void
  /** OCR로 등록한 약 (없으면 null) */
  savedMedication: MedicationDraft | null
  onNavigate: (view: MyPageViewName) => void
  onRegisterMedicine: () => void
}) {
  const profileMedicines = profile.medicines || []
  const medicines = [...profileMedicines, ...(savedMedication ? [savedMedication.name] : [])]
  const shortcuts = [
    { label: "약 등록", icon: Camera, action: onRegisterMedicine },
    { label: "복약 캘린더", icon: CalendarDays, action: () => onNavigate("calendar") },
    { label: "알림 설정", icon: Bell, action: () => onNavigate("notifications") },
    { label: "설정", icon: Settings, action: () => onNavigate("settings") },
  ]

  return (
    <>
      <section className="mb-7 flex items-center gap-4 rounded-2xl bg-blue-50 p-6">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-white text-blue-600">
          <UserRound size={26} />
        </div>
        <div>
          <h2 className="text-xl font-bold">안녕하세요, 데모님</h2>
          <p className="mt-1 text-sm text-slate-500">
            {[
              profile.gender,
              profile.age && `만 ${profile.age}세`,
              profile.height && `${profile.height}cm`,
              profile.weight && `${profile.weight}kg`,
            ]
              .filter(Boolean)
              .join(" · ") || "오늘도 건강한 하루를 함께해요."}
          </p>
        </div>
        <button
          aria-label="프로필 수정"
          onClick={() => onNavigate("profile")}
          className="ml-auto flex h-11 w-11 items-center justify-center"
        >
          <ChevronRight size={20} />
        </button>
      </section>
      <div className="grid grid-cols-2 gap-7">
        <section className="rounded-2xl border p-5">
          <h2 className="mb-4 text-lg font-bold">오늘의 복약 체크리스트</h2>
          {intakeSlots.map((time) => (
            <label key={time} className="flex min-h-16 items-center gap-3 border-b border-slate-100">
              <input
                type="checkbox"
                className="h-5 w-5 accent-emerald-600"
                checked={checked.includes(`7-${time}`)}
                onChange={() => toggleCheck(`7-${time}`)}
              />
              <span className="flex-1">{time}</span>
              <span className="text-sm text-slate-500">가나다정</span>
            </label>
          ))}
        </section>
        <section className="rounded-2xl border p-5">
          <h2 className="mb-4 text-lg font-bold">내 복용약</h2>
          {!medicines.length && (
            <p className="py-4 leading-7 text-slate-500">
              {profile.medicineStatus || "아직 등록한 약이 없어요."}
            </p>
          )}
          {medicines.map((drug, index) => (
            <div key={`${drug}-${index}`} className="flex min-h-20 items-center gap-3">
              <Pill className="text-blue-600" size={22} />
              <div>
                <b className="font-medium">{drug}</b>
                <p className="mt-1 text-sm text-slate-500">
                  {savedMedication && index === profileMedicines.length
                    ? `1회 ${savedMedication.amount}정 · 하루 ${savedMedication.times}회 · ${savedMedication.days}일`
                    : "건강정보에서 등록 · 가상 약 데이터"}
                </p>
              </div>
            </div>
          ))}
        </section>
      </div>
      <section className="mt-7 rounded-2xl border border-slate-200 p-6">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-bold">등록한 지병 정보</h2>
          <button onClick={() => onNavigate("profile")} className="min-h-11 text-blue-600">
            건강정보 수정
          </button>
        </div>
        <p className="mt-2 whitespace-pre-wrap break-words leading-7 text-slate-600">
          {profile.conditions || "아직 입력한 정보가 없어요."}
        </p>
        <p className="mt-3 text-sm text-slate-500">입력한 내용 그대로 표시하며 진단을 제공하지 않습니다.</p>
      </section>
      <div className="mt-7 grid grid-cols-4 gap-4">
        {shortcuts.map((item) => (
          <button
            key={item.label}
            onClick={item.action}
            className="flex min-h-16 items-center gap-3 rounded-xl border p-4 text-left"
          >
            <item.icon size={21} className="text-slate-500" />
            {item.label}
            <ChevronRight size={18} className="ml-auto text-slate-400" />
          </button>
        ))}
      </div>
    </>
  )
}
