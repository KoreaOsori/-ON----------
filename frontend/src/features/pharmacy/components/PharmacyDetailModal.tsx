"use client"

import { useEffect, useState } from "react"
import { Navigation, Phone } from "lucide-react"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { getPharmacy, type Coordinates, type PharmacyDetail, type PharmacyResult } from "../api"
import { kakaoDirectionsUrl, naverPlaceUrl } from "../kakao"
import { formatDistance } from "./PharmacyList"

const linkClass = "flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl text-sm font-medium"

export default function PharmacyDetailModal({
  origin,
  pharmacy,
  onClose,
}: {
  origin: Coordinates
  pharmacy: PharmacyResult
  onClose: () => void
}) {
  const [detail, setDetail] = useState<PharmacyDetail | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    getPharmacy(pharmacy.id)
      .then(setDetail)
      .catch(() => setError(true))
  }, [pharmacy.id])

  return (
    <Modal title={pharmacy.name} close={onClose}>
      <p className="leading-7">{pharmacy.address}</p>
      <p className="mt-1 text-sm text-slate-500">
        {formatDistance(pharmacy.distanceMeters)} · {pharmacy.statusText}
        {pharmacy.phone && ` · ${pharmacy.phone}`}
      </p>
      <div className="my-6 flex gap-2">
        {pharmacy.phone && (
          <a href={`tel:${pharmacy.phone}`} className={`${linkClass} bg-slate-100`}>
            <Phone size={16} />
            전화
          </a>
        )}
        <a
          href={kakaoDirectionsUrl(origin, pharmacy)}
          target="_blank"
          rel="noopener noreferrer"
          className={`${linkClass} bg-blue-600 text-white`}
        >
          <Navigation size={16} />
          카카오맵 길찾기
        </a>
        <a
          href={naverPlaceUrl(pharmacy.name, pharmacy.address)}
          target="_blank"
          rel="noopener noreferrer"
          className={`${linkClass} bg-emerald-50 text-emerald-700`}
        >
          네이버 플레이스
        </a>
      </div>
      <h3 className="mb-3 font-bold">영업시간</h3>
      {error ? (
        <p className="text-sm text-slate-500">영업시간을 불러오지 못했어요.</p>
      ) : !detail ? (
        <p className="text-sm text-slate-500">불러오는 중…</p>
      ) : (
        <>
          <dl className="grid grid-cols-[4rem_1fr] gap-y-2 rounded-xl bg-slate-50 p-4 text-sm">
            {detail.hours.map(({ day, hours }) => (
              <div key={day} className="contents">
                <dt className="text-slate-500">{day}</dt>
                <dd className={hours ? "" : "text-slate-400"}>{hours ?? "휴무 또는 정보 없음"}</dd>
              </div>
            ))}
          </dl>
          {detail.note && <p className="mt-3 text-sm text-slate-600">{detail.note}</p>}
          {detail.directions && <p className="mt-3 text-sm leading-6 text-slate-600">찾아오는 길 · {detail.directions}</p>}
        </>
      )}
      <div className="mt-6">
        <Notice>국립중앙의료원 약국 정보 기준이에요. 공휴일·임시 휴무는 다를 수 있어 방문 전 전화로 확인하세요.</Notice>
      </div>
    </Modal>
  )
}
