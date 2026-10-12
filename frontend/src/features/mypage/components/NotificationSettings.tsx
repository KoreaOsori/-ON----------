"use client"

import { useState } from "react"
import Notice from "@/components/ui/Notice"

const scheduledDrugs = ["가나다정", "라마바정"]
const defaultTimes = ["08:00", "13:00", "19:00"]
const timeLabels = ["아침", "점심", "저녁"]

export default function NotificationSettings() {
  const [push, setPush] = useState(true)
  return (
    <section className="max-w-lg space-y-5">
      <label className="flex min-h-16 items-center justify-between rounded-xl border p-4">
        푸시 알림
        <input
          type="checkbox"
          checked={push}
          onChange={(event) => setPush(event.target.checked)}
          className="h-5 w-5 accent-blue-600"
        />
      </label>
      <Notice>알림 설정 화면의 데모예요. 실제 푸시 알림은 발송되지 않아요.</Notice>
      {scheduledDrugs.map((drug) => (
        <div key={drug} className="rounded-xl border p-5">
          <h3 className="mb-4 font-semibold">{drug} 복용 시간</h3>
          <div className="grid grid-cols-3 gap-3">
            {defaultTimes.map((time, index) => (
              <label className="text-xs text-slate-500" key={time}>
                {timeLabels[index]}
                <input
                  type="time"
                  defaultValue={time}
                  className="mt-2 min-h-11 w-full rounded-lg border px-2 text-sm"
                />
              </label>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
