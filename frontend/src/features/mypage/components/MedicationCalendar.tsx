"use client"

import { useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { checkKey, scheduleOn, toDateString, type RegisteredMedication } from "../types"

const weekdays = ["일", "월", "화", "수", "목", "금", "토"]

// 월간 복약 캘린더. 약 등록으로 저장한 복용 일정과 체크 기록(브라우저 저장)으로 그린다
export default function MedicationCalendar({
  checked,
  toggleCheck,
  medications,
}: {
  checked: string[]
  toggleCheck: (key: string) => void
  medications: RegisteredMedication[]
}) {
  const today = toDateString(new Date())
  const [month, setMonth] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [day, setDay] = useState(today)
  const lastDate = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const dateOf = (date: number) => toDateString(new Date(month.getFullYear(), month.getMonth(), date))
  const moveMonth = (offset: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + offset, 1))

  // 지난 날(오늘 포함): 먹을 약이 있는 시점을 모두 체크했으면 완료, 아니면 누락 (오늘은 다 체크했을 때만 표시)
  const status = (date: string) => {
    const slots = scheduleOn(medications, date)
    if (!slots.length || date > today) return null
    const done = slots.every((item) => checked.includes(checkKey(date, item.slot)))
    if (done) return "done"
    return date < today ? "missed" : null
  }
  const daySchedule = scheduleOn(medications, day)
  const [, dayMonth, dayDate] = day.split("-").map(Number)

  return (
    <section className="mx-auto max-w-lg">
      <div className="mb-5 flex items-center justify-between">
        <button aria-label="이전 달" onClick={() => moveMonth(-1)} className="flex h-11 w-11 items-center justify-center">
          <ChevronLeft size={20} />
        </button>
        <h2 className="text-xl font-bold">
          {month.getFullYear()}년 {month.getMonth() + 1}월
        </h2>
        <button aria-label="다음 달" onClick={() => moveMonth(1)} className="flex h-11 w-11 items-center justify-center">
          <ChevronRight size={20} />
        </button>
      </div>
      <div className="grid grid-cols-7 rounded-2xl border p-3">
        {weekdays.map((item) => (
          <div key={item} className="py-3 text-center text-sm text-slate-500">
            {item}
          </div>
        ))}
        {Array.from({ length: month.getDay() }).map((_, index) => (
          <span key={`empty-${index}`} />
        ))}
        {Array.from({ length: lastDate }, (_, index) => index + 1).map((date) => {
          const value = dateOf(date)
          const mark = status(value)
          return (
            <button
              key={date}
              onClick={() => setDay(value)}
              className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl ${
                day === value ? "bg-blue-600 text-white" : ""
              }`}
            >
              {date}
              {mark && (
                <span
                  className={`h-1.5 w-1.5 rounded-full ${mark === "missed" ? "bg-amber-500" : "bg-emerald-500"}`}
                />
              )}
            </button>
          )
        })}
      </div>
      <p className="my-3 text-xs text-slate-500">🟢 복용 완료 · 🟠 누락</p>
      <h3 className="mb-3 mt-7 font-semibold">
        {dayMonth}월 {dayDate}일 복약 목록
      </h3>
      {!daySchedule.length && (
        <p className="py-4 leading-7 text-slate-500">
          {medications.length ? "이 날 복용할 약이 없어요." : "약 등록에서 복용 일정을 등록해 주세요."}
        </p>
      )}
      {daySchedule.map(({ slot, names }) => (
        <label key={slot} className="flex min-h-16 items-center gap-3 border-b">
          <input
            type="checkbox"
            className="h-5 w-5 accent-emerald-600"
            checked={checked.includes(checkKey(day, slot))}
            onChange={() => toggleCheck(checkKey(day, slot))}
          />
          {slot}
          <span className="ml-auto text-right text-sm text-slate-500">{names.join(", ")}</span>
        </label>
      ))}
    </section>
  )
}
