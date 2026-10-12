"use client"

import { useState } from "react"
import { intakeSlots } from "../types"

const weekdays = ["일", "월", "화", "수", "목", "금", "토"]

// 예시 월간 캘린더 (2026년 10월 고정). 백엔드 GET /api/v1/medications/logs 연동 시 실제 기록으로 교체한다.
export default function MedicationCalendar({
  checked,
  toggleCheck,
}: {
  checked: string[]
  toggleCheck: (key: string) => void
}) {
  const [day, setDay] = useState(7)
  return (
    <section className="mx-auto max-w-lg">
      <div className="mb-5 flex items-center justify-between">
        <h2 className="text-xl font-bold">2026년 10월</h2>
        <span className="text-xs text-slate-500">예시 월간 캘린더</span>
      </div>
      <div className="grid grid-cols-7 rounded-2xl border p-3">
        {weekdays.map((item) => (
          <div key={item} className="py-3 text-center text-sm text-slate-500">
            {item}
          </div>
        ))}
        {Array.from({ length: 4 }).map((_, index) => (
          <span key={`empty-${index}`} />
        ))}
        {Array.from({ length: 31 }, (_, index) => index + 1).map((date) => (
          <button
            key={date}
            onClick={() => setDay(date)}
            className={`flex min-h-14 flex-col items-center justify-center gap-1 rounded-xl ${
              day === date ? "bg-blue-600 text-white" : ""
            }`}
          >
            {date}
            {date < 7 && (
              <span
                className={`h-1.5 w-1.5 rounded-full ${date === 4 ? "bg-amber-500" : "bg-emerald-500"}`}
              />
            )}
            {date === 7 && checked.some((item) => item.startsWith("7-")) && (
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            )}
          </button>
        ))}
      </div>
      <p className="my-3 text-xs text-slate-500">🟢 복용 완료 · 🟠 누락 (예시 기록)</p>
      <h3 className="mb-3 mt-7 font-semibold">10월 {day}일 복약 목록</h3>
      {intakeSlots.map((time) => (
        <label key={time} className="flex min-h-16 items-center gap-3 border-b">
          <input
            type="checkbox"
            className="h-5 w-5 accent-emerald-600"
            checked={checked.includes(`${day}-${time}`)}
            onChange={() => toggleCheck(`${day}-${time}`)}
          />
          {time}
          <span className="ml-auto text-sm text-slate-500">가나다정</span>
        </label>
      ))}
    </section>
  )
}
