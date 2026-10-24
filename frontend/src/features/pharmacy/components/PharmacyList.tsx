import { Navigation, Phone } from "lucide-react"
import type { Coordinates, PharmacyResult } from "../api"
import { kakaoDirectionsUrl } from "../kakao"

export const formatDistance = (meters: number) =>
  meters < 1000 ? `${meters}m` : `${(meters / 1000).toFixed(1)}km`

const statusColor = (pharmacy: PharmacyResult) =>
  pharmacy.isOpen ? "text-emerald-700" : pharmacy.statusText.startsWith("영업 전") ? "text-amber-700" : "text-slate-500"

export default function PharmacyList({
  origin,
  pharmacies,
  openOnly,
  onToggleOpenOnly,
  selectedId,
  onSelect,
  onOpenDetail,
}: {
  origin: Coordinates
  pharmacies: PharmacyResult[]
  openOnly: boolean
  onToggleOpenOnly: () => void
  selectedId: string | null
  onSelect: (id: string) => void
  onOpenDetail: (id: string) => void
}) {
  const visible = openOnly ? pharmacies.filter((pharmacy) => pharmacy.isOpen) : pharmacies
  return (
    <section>
      <div className="mb-4 flex gap-2">
        <button
          onClick={onToggleOpenOnly}
          aria-pressed={openOnly}
          className={`min-h-11 rounded-full border px-4 text-sm ${
            openOnly ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-200"
          }`}
        >
          지금 영업 중
        </button>
        <span className="flex items-center rounded-full bg-slate-100 px-4 text-sm">거리순 · {visible.length}곳</span>
      </div>
      <p className="mb-4 text-xs leading-6 text-slate-500">
        약국이 신고한 영업시간 기준이며, 공휴일은 다를 수 있어 방문 전 전화로 확인하세요.
      </p>
      {!visible.length && (
        <p className="py-10 text-center text-sm text-slate-500">
          {openOnly ? "지금 영업 중인 약국이 근처에 없어요." : "주변에 약국이 없어요."}
        </p>
      )}
      <div className="space-y-3 lg:max-h-[560px] lg:overflow-y-auto lg:pr-1">
        {visible.map((pharmacy) => (
          <article
            key={pharmacy.id}
            className={`rounded-2xl border p-5 ${selectedId === pharmacy.id ? "border-blue-400 ring-2 ring-blue-100" : ""}`}
          >
            <button onClick={() => onSelect(pharmacy.id)} className="block w-full text-left">
              <div className="flex justify-between gap-3">
                <h3 className="font-bold">{pharmacy.name}</h3>
                <span className="shrink-0 text-sm text-blue-600">{formatDistance(pharmacy.distanceMeters)}</span>
              </div>
              <p className="my-2 text-sm text-slate-500">{pharmacy.address}</p>
              <p className="text-sm">
                <span className={statusColor(pharmacy)}>{pharmacy.statusText}</span>
                {pharmacy.todayHours && <span className="text-slate-500"> · 오늘 {pharmacy.todayHours}</span>}
              </p>
            </button>
            <div className="mt-4 flex gap-2">
              {pharmacy.phone && (
                <a
                  href={`tel:${pharmacy.phone}`}
                  className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-slate-50 text-sm"
                >
                  <Phone size={15} />
                  전화
                </a>
              )}
              <a
                href={kakaoDirectionsUrl(origin, pharmacy)}
                target="_blank"
                rel="noopener noreferrer"
                className="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-blue-50 text-sm text-blue-600"
              >
                <Navigation size={15} />
                길찾기
              </a>
              <button
                onClick={() => onOpenDetail(pharmacy.id)}
                className="min-h-11 flex-1 rounded-lg bg-slate-50 text-sm"
              >
                상세
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
