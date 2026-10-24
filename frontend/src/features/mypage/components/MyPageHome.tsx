import { Bell, CalendarDays, Camera, ChevronRight, Pill, Settings, UserRound } from "lucide-react"
import type { HealthProfile } from "@/types/health"
import { dosageText, intakeItemsOn, isFinished, myMedicines, today } from "../medications"
import type { MyPageViewName } from "../types"

export default function MyPageHome({
  profile,
  checked,
  toggleCheck,
  onNavigate,
  onRegisterMedicine,
  onManageMedicines,
}: {
  profile: HealthProfile
  checked: string[]
  toggleCheck: (key: string) => void
  onNavigate: (view: MyPageViewName) => void
  onRegisterMedicine: () => void
  onManageMedicines: () => void
}) {
  const medicines = myMedicines(profile)
  // 오늘 먹을 약: 복용 기간 안의 약을 하루 횟수에 맞춰 시간대별로 나눈다
  const date = today()
  const checklist = intakeItemsOn(profile, date)
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
          <h2 className="text-xl font-bold">안녕하세요{profile.displayName ? `, ${profile.displayName}님` : ""}</h2>
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
          {!checklist.length && (
            <p className="py-4 leading-7 text-slate-500">
              {medicines.length
                ? "오늘 먹을 약이 없어요. 복용 기간이 끝난 약은 내 복용약에서 정리할 수 있어요."
                : "내 복용약을 등록하면 오늘 먹을 약이 여기에 표시돼요."}
            </p>
          )}
          {checklist.map((item) => (
            <label key={item.key} className="flex min-h-16 items-center gap-3 border-b border-slate-100">
              <input
                type="checkbox"
                className="h-5 w-5 shrink-0 accent-emerald-600"
                checked={checked.includes(item.key)}
                onChange={() => toggleCheck(item.key)}
              />
              <span className="w-20 shrink-0">{item.slot}</span>
              <span className="ml-auto truncate text-right text-sm text-slate-500">{item.name}</span>
            </label>
          ))}
        </section>
        <section className="rounded-2xl border p-5">
          <button
            onClick={onManageMedicines}
            className="mb-2 flex min-h-11 w-full items-center justify-between text-left"
            aria-label="내 복용약 관리 열기"
          >
            <h2 className="text-lg font-bold">내 복용약</h2>
            <span className="flex items-center gap-1 text-sm text-slate-500">
              {medicines.length ? `${medicines.length}개 · 관리` : "추가하기"}
              <ChevronRight size={20} />
            </span>
          </button>
          {!medicines.length && (
            <p className="py-4 leading-7 text-slate-500">아직 등록한 약이 없어요.</p>
          )}
          {medicines.map((drug) => (
            <button
              key={drug.name}
              onClick={onManageMedicines}
              className="flex min-h-20 w-full items-center gap-3 rounded-xl px-1 text-left hover:bg-slate-50"
            >
              <Pill className="shrink-0 text-blue-600" size={22} />
              <div className="min-w-0">
                <b className="break-words font-medium">{drug.name}</b>
                <p className="mt-1 text-sm text-slate-600">
                  {drug.info && dosageText(drug.info) ? dosageText(drug.info) : "복용 정보 없음 · 눌러서 입력할 수 있어요"}
                </p>
                <p className="text-xs text-slate-400">
                  {drug.source}
                  {isFinished(drug.info, date) && <span className="ml-2 text-amber-700">복용 기간 끝남</span>}
                </p>
              </div>
            </button>
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
