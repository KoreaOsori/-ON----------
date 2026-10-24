"use client"

import { useState } from "react"
import { LoaderCircle } from "lucide-react"
import { button } from "@/components/ui/styles"
import { findNearbyPharmacies, type Coordinates, type PharmacyResult } from "../api"
import { findCoordinates } from "../kakao"
import LocationRequest from "./LocationRequest"
import PharmacyDetailModal from "./PharmacyDetailModal"
import PharmacyList from "./PharmacyList"
import PharmacyMap from "./PharmacyMap"

type State =
  | { kind: "request"; message: string | null }
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; origin: Coordinates; pharmacies: PharmacyResult[] }

// 위치 권한 오류 코드 (GeolocationPositionError)
const PERMISSION_DENIED = 1

export default function PharmacyView() {
  const [state, setState] = useState<State>({ kind: "request", message: null })
  const [openOnly, setOpenOnly] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)

  const load = async (origin: Coordinates) => {
    setState({ kind: "loading" })
    setSelectedId(null)
    try {
      setState({ kind: "ready", origin, pharmacies: await findNearbyPharmacies(origin) })
    } catch {
      setState({ kind: "error" })
    }
  }

  const requestMyLocation = () => {
    // 브라우저는 https(또는 localhost)에서만 위치 권한을 물어본다
    if (!window.isSecureContext || !navigator.geolocation) {
      setState({ kind: "request", message: "이 접속 환경에서는 위치를 사용할 수 없어요. 주소나 장소 이름으로 찾아주세요." })
      return
    }
    setState({ kind: "loading" })
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => load({ lat: coords.latitude, lng: coords.longitude }),
      (error) =>
        setState({
          kind: "request",
          message:
            error.code === PERMISSION_DENIED
              ? "위치 권한이 꺼져 있어요. 브라우저 주소창의 사이트 설정에서 위치를 허용하거나 주소로 찾아주세요."
              : "현재 위치를 확인하지 못했어요. 다시 시도하거나 주소로 찾아주세요.",
        }),
      { timeout: 10000, maximumAge: 60000 },
    )
  }

  const searchAddress = async (address: string) => {
    setState({ kind: "loading" })
    const origin = await findCoordinates(address).catch(() => null)
    if (origin) await load(origin)
    else setState({ kind: "request", message: `"${address}" 위치를 찾지 못했어요. 도로명 주소나 역 이름으로 다시 찾아보세요.` })
  }

  const detail = state.kind === "ready" ? state.pharmacies.find((item) => item.id === detailId) : undefined

  return (
    <>
      <h1 className="text-3xl font-bold">내 주변 약국</h1>
      <p className="mt-3 text-slate-500">가까운 약국을 찾고, 방문 전 확인해 보세요.</p>
      {state.kind === "request" ? (
        <LocationRequest
          message={state.message}
          onUseLocation={requestMyLocation}
          onSearchAddress={searchAddress}
        />
      ) : state.kind === "loading" ? (
        <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-slate-500">
          <LoaderCircle className="animate-spin" />
          주변 약국을 찾는 중이에요
        </div>
      ) : state.kind === "error" ? (
        <div className="py-20 text-center">
          <p>약국 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.</p>
          <button onClick={() => setState({ kind: "request", message: null })} className={`${button} mt-6`}>
            다시 찾기
          </button>
        </div>
      ) : (
        <>
          <button
            onClick={() => setState({ kind: "request", message: null })}
            className="mt-4 min-h-11 text-sm text-blue-600"
          >
            다른 위치로 찾기
          </button>
          <div className="mt-4 grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
            <div className="order-2 lg:order-1">
              <PharmacyList
                origin={state.origin}
                pharmacies={state.pharmacies}
                openOnly={openOnly}
                onToggleOpenOnly={() => setOpenOnly(!openOnly)}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onOpenDetail={setDetailId}
              />
            </div>
            <div className="order-1 lg:order-2">
              <PharmacyMap
                origin={state.origin}
                pharmacies={state.pharmacies}
                selectedId={selectedId}
                onSelect={(id) => {
                  setSelectedId(id)
                  setDetailId(id)
                }}
              />
            </div>
          </div>
        </>
      )}
      {state.kind === "ready" && detail && (
        <PharmacyDetailModal origin={state.origin} pharmacy={detail} onClose={() => setDetailId(null)} />
      )}
    </>
  )
}
