"use client"

import { useState } from "react"
import { MapPin } from "lucide-react"
import { button, inputClass } from "@/components/ui/styles"

export default function LocationRequest({
  denied,
  onUseLocation,
  onDeny,
  onSearchAddress,
  onDemo,
}: {
  /** 위치 권한이 없을 때는 주소 입력 폼을 보여준다 */
  denied: boolean
  onUseLocation: () => void
  onDeny: () => void
  onSearchAddress: (address: string) => void
  onDemo: () => void
}) {
  const [address, setAddress] = useState("")
  return (
    <section className="mx-auto max-w-md py-16 text-center">
      <div className="mx-auto mb-6 flex h-24 w-24 items-center justify-center rounded-3xl bg-emerald-50 text-emerald-600">
        <MapPin size={44} strokeWidth={1.4} />
      </div>
      <h2 className="text-2xl font-bold">가까운 약국을 찾아드릴게요</h2>
      <p className="mb-7 mt-4 leading-7 text-slate-500">
        {denied
          ? "위치를 사용할 수 없어요. 주소로 직접 찾아주세요."
          : "내 위치를 사용하면 주변 약국을 거리순으로 볼 수 있어요."}
      </p>
      {!denied ? (
        <>
          <button className={`${button} w-full`} onClick={onUseLocation}>
            내 위치 사용하기
          </button>
          <button
            onClick={onDeny}
            className="mt-4 min-h-11 text-slate-500 underline underline-offset-4"
          >
            주소로 직접 찾기
          </button>
          <button onClick={onDemo} className="mt-5 block min-h-11 w-full text-sm text-blue-600">
            위치 권한 없이 데모 지도 보기
          </button>
        </>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            onSearchAddress(address)
          }}
          className="space-y-3"
        >
          <input
            aria-label="주소"
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder="시·구 또는 도로명 주소"
            className={inputClass}
            required
          />
          <button className={`${button} w-full`}>주소로 찾기</button>
        </form>
      )}
    </section>
  )
}
