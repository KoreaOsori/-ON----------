import { Bell, CalendarDays, Camera, ChevronRight, Pill, Settings, UserRound } from "lucide-react"
import type { HealthProfile, RegisteredMedication } from "@/types/health"
import { intakeSlots, type MyPageViewName } from "../types"

/** 복용 정보 한 줄: 1일 3회 · 1회 1정 · 7일분 (모르는 값은 빼고 표시) */
const dosageText = (item: RegisteredMedication) =>
  [
    item.times && `1일 ${item.times}회`,
    item.amount && `1회 ${item.amount}정`,
    item.days && `${item.days}일분`,
    item.start && `${item.start} 시작`,
  ]
    .filter(Boolean)
    .join(" · ")

export default function MyPageHome({
  profile,
  checked,
  toggleCheck,
  onNavigate,
  onRegisterMedicine,
}: {
  profile: HealthProfile
  checked: string[]
  toggleCheck: (key: string) => void
  onNavigate: (view: MyPageViewName) => void
  onRegisterMedicine: () => void
}) {
  // 건강정보에서 고른 약 + 약 등록(처방전 인식)으로 저장한 약. 같은 이름이면 하나로 합치고 복용 정보를 붙인다
  const registered = profile.registeredMedications ?? []
  const byName = new Map(registered.map((item) => [item.name, item]))
  const profileMedicines = profile.medicines || []
  const medicines = [
    ...profileMedicines.map((name) => ({ name, info: byName.get(name), source: "건강정보에서 등록" })),
    ...registered
      .filter((item) => !profileMedicines.includes(item.name))
      .map((item) => ({ name: item.name, info: item, source: "약 등록(처방전 인식)" })),
  ]
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
          {medicines.map((drug) => (
            <div key={drug.name} className="flex min-h-20 items-center gap-3">
              <Pill className="shrink-0 text-blue-600" size={22} />
              <div>
                <b className="font-medium">{drug.name}</b>
                <p className="mt-1 text-sm text-slate-600">
                  {drug.info ? dosageText(drug.info) : "복용 정보 없음 · 약 등록에서 입력할 수 있어요"}
                </p>
                <p className="text-xs text-slate-400">{drug.source}</p>
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
