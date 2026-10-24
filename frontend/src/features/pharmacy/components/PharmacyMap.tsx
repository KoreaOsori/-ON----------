"use client"

import { useEffect, useRef, useState } from "react"
import type { Coordinates, PharmacyResult } from "../api"
import { hasMapKey, loadKakaoMaps, type KakaoMap, type KakaoMarker } from "../kakao"

// 처음 화면에 맞출 가까운 약국 수 (전부 넣으면 너무 넓어진다)
const FIT_COUNT = 8

export default function PharmacyMap({
  origin,
  pharmacies,
  selectedId,
  onSelect,
}: {
  origin: Coordinates
  pharmacies: PharmacyResult[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<KakaoMap | null>(null)
  const markers = useRef(new Map<string, KakaoMarker>())
  const [failed, setFailed] = useState(!hasMapKey)
  // 마커 클릭 핸들러가 항상 최신 onSelect 를 부르도록
  const select = useRef(onSelect)
  useEffect(() => {
    select.current = onSelect
  }, [onSelect])

  useEffect(() => {
    let cancelled = false
    const drawn = markers.current
    loadKakaoMaps()
      .then(({ maps }) => {
        if (cancelled || !container.current) return
        const center = new maps.LatLng(origin.lat, origin.lng)
        const instance = new maps.Map(container.current, { center, level: 4 })
        map.current = instance

        const me = document.createElement("div")
        me.className = "h-5 w-5 rounded-full border-[3px] border-white bg-blue-600 shadow ring-8 ring-blue-500/25"
        me.title = "내 위치"
        new maps.CustomOverlay({ position: center, content: me, map: instance, zIndex: 3 })

        const bounds = new maps.LatLngBounds()
        bounds.extend(center)
        pharmacies.forEach((pharmacy, order) => {
          const position = new maps.LatLng(pharmacy.latitude, pharmacy.longitude)
          const marker = new maps.Marker({ position, title: pharmacy.name, map: instance })
          maps.event.addListener(marker, "click", () => select.current(pharmacy.id))
          drawn.set(pharmacy.id, marker)
          if (order < FIT_COUNT) bounds.extend(position)
        })
        if (pharmacies.length) instance.setBounds(bounds)
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      drawn.forEach((marker) => marker.setMap(null))
      drawn.clear()
      map.current = null
    }
  }, [origin, pharmacies])

  useEffect(() => {
    const pharmacy = pharmacies.find((item) => item.id === selectedId)
    if (!pharmacy || !map.current || !window.kakao) return
    map.current.panTo(new window.kakao.maps.LatLng(pharmacy.latitude, pharmacy.longitude))
    markers.current.forEach((marker, id) => marker.setZIndex(id === selectedId ? 2 : 1))
  }, [selectedId, pharmacies])

  if (failed) {
    return (
      <div className="flex min-h-80 items-center justify-center rounded-2xl border border-slate-200 bg-slate-50 p-6 text-center text-sm leading-6 text-slate-500 lg:min-h-[620px]">
        지도를 불러오지 못했어요. 목록과 길찾기는 그대로 이용할 수 있어요.
      </div>
    )
  }
  return (
    <div
      ref={container}
      aria-label="주변 약국 지도"
      className="min-h-80 overflow-hidden rounded-2xl border border-slate-200 bg-slate-100 lg:sticky lg:top-6 lg:h-[620px]"
    />
  )
}
