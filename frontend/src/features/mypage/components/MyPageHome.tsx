import { Bell, CalendarDays, Camera, ChevronRight, Pill, Settings, UserRound } from "lucide-react"
import type { HealthProfile } from "@/types/health"
import {
  checkKey,
  isTakingOn,
  scheduleOn,
  toDateString,
  type MyPageViewName,
  type RegisteredMedication,
} from "../types"

export default function MyPageHome({
  profile,
  checked,
  toggleCheck,
  medications,
  onNavigate,
  onRegisterMedicine,
}: {
  profile: HealthProfile
  checked: string[]
  toggleCheck: (key: string) => void
  /** 약 등록으로 저장한 복용약·일정 */
  medications: RegisteredMedication[]
  onNavigate: (view: MyPageViewName) => void
  onRegisterMedicine: () => void
}) {
  const today = toDateString(new Date())
  const todaySchedule = scheduleOn(medications, today)
  // 건강정보에서 고른 약 (일정 없음) + 약 등록으로 넣은 약 (일정 있음)
  const medicines = [
    ...(profile.medicines || []).map((name) => ({ name, detail: "건강정보에서 등록" })),
    ...medications.map((medication) => ({
      name: medication.name,
      detail: `1회 ${medication.amount}정 · 하루 ${medication.times}회 · ${medication.days}일 (${medication.start}부터)${
        isTakingOn(medication, today) ? "" : " · 오늘은 복용 기간 아님"
      }`,
    })),
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
          {!todaySchedule.length && (
            <p className="py-4 leading-7 text-slate-500">
              {medications.length
                ? "오늘 복용할 약이 없어요."
                : "약 등록에서 복용 일정을 등록하면 여기에 나와요."}
            </p>
          )}
          {todaySchedule.map(({ slot, names }) => (
            <label key={slot} className="flex min-h-16 items-center gap-3 border-b border-slate-100">
              <input
                type="checkbox"
                className="h-5 w-5 accent-emerald-600"
                checked={checked.includes(checkKey(today, slot))}
                onChange={() => toggleCheck(checkKey(today, slot))}
              />
              <span className="flex-1">{slot}</span>
              <span className="text-right text-sm text-slate-500">{names.join(", ")}</span>
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
            <div key={`${drug.name}-${index}`} className="flex min-h-20 items-center gap-3">
              <Pill className="text-blue-600" size={22} />
              <div>
                <b className="font-medium">{drug.name}</b>
                <p className="mt-1 text-sm text-slate-500">{drug.detail}</p>
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
