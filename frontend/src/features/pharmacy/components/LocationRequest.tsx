"use client"

import { useState } from "react"
import { MapPin } from "lucide-react"
import { button, inputClass } from "@/components/ui/styles"

export default function LocationRequest({
  message,
  onUseLocation,
  onSearchAddress,
}: {
  /** 위치를 쓸 수 없을 때 이유 (없으면 위치 사용 동의 안내) */
  message: string | null
  onUseLocation: () => void
  onSearchAddress: (address: string) => void
}) {
  const [address, setAddress] = useState("")
  return (
    <section className="mx-auto max-w-md py-16 text-center">
      <div className="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl bg-emerald-50 text-emerald-600">
        <MapPin size={44} strokeWidth={1.4} />
      </div>
      <h2 className="text-2xl font-bold">가까운 약국을 찾아드릴게요</h2>
      <p className="mb-7 mt-4 leading-7 text-slate-500">
        {message ?? "위치 사용에 동의하면 현재 위치에서 가까운 약국을 거리순으로 보여드려요. 위치는 약국 검색에만 쓰고 저장하지 않아요."}
      </p>
      <button className={`${button} w-full`} onClick={onUseLocation}>
        내 위치 사용하기
      </button>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onSearchAddress(address.trim())
        }}
        className="mt-8 space-y-3 border-t pt-8 text-left"
      >
        <label htmlFor="pharmacy-address" className="text-sm text-slate-500">
          또는 주소·장소로 찾기
        </label>
        <input
          id="pharmacy-address"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="예: 테헤란로 101, 강남역"
          className={inputClass}
          required
        />
        <button className="min-h-12 w-full rounded-xl border border-slate-200 font-medium">
          주소로 찾기
        </button>
      </form>
    </section>
  )
}
