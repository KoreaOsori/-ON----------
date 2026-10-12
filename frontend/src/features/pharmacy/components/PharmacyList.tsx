import { Navigation, Phone } from "lucide-react"
import type { Pharmacy } from "@/types/pharmacy"

export default function PharmacyList({
  pharmacies,
  openOnly,
  onToggleOpenOnly,
  onSelect,
}: {
  pharmacies: Pharmacy[]
  openOnly: boolean
  onToggleOpenOnly: () => void
  onSelect: (index: number) => void
}) {
  return (
    <section>
      <div className="mb-4 flex gap-2">
        <button
          onClick={onToggleOpenOnly}
          className={`min-h-11 rounded-full border px-4 text-sm ${
            openOnly ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200"
          }`}
        >
          지금 영업 중
        </button>
        <span className="flex items-center rounded-full bg-slate-100 px-4 text-sm">거리순</span>
      </div>
      <p className="mb-4 text-xs leading-6 text-slate-500">
        약국이 신고한 영업시간 기준이며, 방문 전 전화로 확인하세요.
      </p>
      {pharmacies
        .map((pharmacy, index) => ({ pharmacy, index }))
        .filter(({ pharmacy }) => !openOnly || pharmacy.status.includes("영업 중"))
        .map(({ pharmacy, index }) => (
          <article key={pharmacy.name} className="mb-3 rounded-2xl border p-5">
            <div className="flex justify-between">
              <h3 className="font-bold">{pharmacy.name}</h3>
              <span className="text-sm text-blue-600">{pharmacy.distance}</span>
            </div>
            <p className="my-2 text-sm text-slate-500">{pharmacy.address}</p>
            <span
              className={`text-sm ${
                pharmacy.status.includes("영업 중")
                  ? "text-emerald-700"
                  : pharmacy.status === "오늘 휴무"
                    ? "text-red-600"
                    : "text-slate-500"
              }`}
            >
              {pharmacy.status}
            </span>
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => onSelect(index)}
                className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-slate-50 text-sm"
              >
                <Phone size={15} />
                전화
              </button>
              <button
                onClick={() => onSelect(index)}
                className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-blue-50 text-sm text-blue-600"
              >
                <Navigation size={15} />
                길찾기
              </button>
            </div>
          </article>
        ))}
    </section>
  )
}
