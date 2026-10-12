import { Plus } from "lucide-react"
import type { Pharmacy } from "@/types/pharmacy"

// 정적 지도 목업. 실제 지도 SDK(카카오/네이버 지도) 연동 시 이 컴포넌트를 교체한다.
const markerPositions = ["left-[25%] top-[30%]", "right-[20%] top-[48%]", "left-[32%] bottom-[20%]"]

export default function PharmacyMap({
  pharmacies,
  onSelect,
}: {
  pharmacies: Pharmacy[]
  onSelect: (index: number) => void
}) {
  return (
    <div className="relative flex min-h-[620px] overflow-hidden rounded-2xl border border-slate-200 bg-[#edf2ed]">
      <div className="absolute inset-y-0 left-1/3 w-9 rotate-12 border-x border-slate-200 bg-white" />
      <div className="absolute inset-x-0 top-1/3 h-12 -rotate-12 border-y border-slate-200 bg-white" />
      <div className="absolute inset-y-0 right-1/4 w-5 -rotate-12 bg-white" />
      <div className="absolute inset-x-0 bottom-1/4 h-5 rotate-6 bg-white" />
      <span className="absolute right-7 top-8 rounded-xl bg-green-200/60 p-7 text-sm text-green-800">
        온유공원
      </span>
      <span className="absolute left-8 top-6 rounded-lg bg-white/90 px-3 py-2 text-xs text-slate-500">
        정적 지도 · 가상 위치
      </span>
      <div className="absolute left-1/2 top-1/2 flex h-6 w-6 items-center justify-center rounded-full bg-blue-200 ring-8 ring-blue-200/40">
        <span className="h-3 w-3 rounded-full border-2 border-white bg-blue-600" />
      </div>
      <div className="absolute bottom-8 left-[42%] text-xs font-medium text-blue-700">내 위치</div>
      {markerPositions.map((position, index) => (
        <button
          key={position}
          aria-label={pharmacies[index].name}
          onClick={() => onSelect(index)}
          className={`absolute ${position} flex h-12 w-12 items-center justify-center rounded-full border-4 border-white bg-emerald-600 text-white shadow-md`}
        >
          <Plus size={24} />
        </button>
      ))}
    </div>
  )
}
