"use client"

import { useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import type { HealthProfile } from "@/types/health"
import { intakeItemsOn, today } from "../medications"

const weekdays = ["일", "월", "화", "수", "목", "금", "토"]

const pad = (value: number) => String(value).padStart(2, "0")
const dateOf = (year: number, month: number, day: number) => `${year}-${pad(month + 1)}-${pad(day)}`

// 내 복용약(시작일·복용 일수)과 복약 체크 기록(profile.intakeChecks)으로 그리는 월간 캘린더
export default function MedicationCalendar({
  profile,
  checked,
  toggleCheck,
}: {
  profile: HealthProfile
  checked: string[]
  toggleCheck: (key: string) => void
}) {
  const now = today()
  const [month, setMonth] = useState(() => ({ year: Number(now.slice(0, 4)), month: Number(now.slice(5, 7)) - 1 }))
  const [selected, setSelected] = useState(now)
  const firstWeekday = new Date(month.year, month.month, 1).getDay()
  const lastDay = new Date(month.year, month.month + 1, 0).getDate()

  const move = (offset: number) => {
    const next = new Date(month.year, month.month + offset, 1)
    setMonth({ year: next.getFullYear(), month: next.getMonth() })
  }

  // 오늘까지의 날만 표시: 모두 먹었으면 초록, 하나라도 빠졌으면 주황 (오늘은 아직 남은 복용이 있을 수 있어 초록만)
  const mark = (date: string) => {
    if (date > now) return null
    const items = intakeItemsOn(profile, date)
    if (!items.length) return null
    const done = items.filter((item) => checked.includes(item.key)).length
    if (done === items.length) return "bg-emerald-500"
    return date < now ? "bg-amber-500" : null
  }

  const items = intakeItemsOn(profile, selected)
  const [, selectedMonth, selectedDay] = selected.split("-").map(Number)

  return (
    <section className="mx-auto max-w-lg">
      <div className="mb-5 flex items-center justify-between">
        <button
          aria-label="이전 달"
          onClick={() => move(-1)}
          className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-slate-50"
        >
          <ChevronLeft size={20} />
        </button>
        <h2 className="text-xl font-bold">
          {month.year}년 {month.month + 1}월
        </h2>
        <button
          aria-label="다음 달"
          onClick={() => move(1)}
          className="flex h-11 w-11 items-center justify-center rounded-full hover:bg-slate-50"
        >
          <ChevronRight size={20} />
        </button>
      </div>
      <div className="grid grid-cols-7 rounded-2xl border p-3">
        {weekdays.map((item) => (
          <div key={item} className="py-3 text-center text-sm text-slate-500">
            {item}
          </div>
        ))}
        {Array.from({ length: firstWeekday }).map((_, index) => (
          <span key={`empty-${index}`} />
        ))}
        {Array.from({ length: lastDay }, (_, index) => index + 1).map((day) => {
          const date = dateOf(month.year, month.month, day)
          const dot = mark(date)
          return (
            <button
              key={date}
              onClick={() => setSelected(date)}
              aria-label={`${month.month + 1}월 ${day}일`}
              aria-pressed={selected === date}
              className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl ${
                selected === date ? "bg-blue-600 text-white" : date === now ? "font-bold text-blue-600" : ""
              }`}
            >
              {day}
              <span className={`h-1.5 w-1.5 rounded-full ${dot ?? "bg-transparent"}`} />
            </button>
          )
        })}
      </div>
      <p className="my-3 text-xs text-slate-500">🟢 모두 복용 · 🟠 빠진 복용 있음 (체크한 기록 기준)</p>
      <h3 className="mb-3 mt-7 font-semibold">
        {selectedMonth}월 {selectedDay}일 복약 목록
      </h3>
      {!items.length && <p className="py-4 text-sm text-slate-500">이날 먹는 약이 없어요.</p>}
      {selected > now && items.length > 0 && (
        <p className="mb-2 text-xs text-slate-500">아직 오지 않은 날이라 체크할 수 없어요.</p>
      )}
      {items.map((item) => (
        <label key={item.key} className="flex min-h-16 items-center gap-3 border-b">
          <input
            type="checkbox"
            className="h-5 w-5 shrink-0 accent-emerald-600"
            disabled={selected > now}
            checked={checked.includes(item.key)}
            onChange={() => toggleCheck(item.key)}
          />
          <span className="w-20 shrink-0">{item.slot}</span>
          <span className="ml-auto truncate text-right text-sm text-slate-500">{item.name}</span>
        </label>
      ))}
    </section>
  )
}
