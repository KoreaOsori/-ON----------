"use client"

import { useState } from "react"
import { LoaderCircle } from "lucide-react"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { button } from "@/components/ui/styles"
import { pharmacies } from "@/mocks/pharmacies"
import LocationRequest from "./LocationRequest"
import PharmacyList from "./PharmacyList"
import PharmacyMap from "./PharmacyMap"

type PharmacyState = "permission" | "denied" | "loading" | "empty" | "error" | "map"

export default function PharmacyView() {
  const [state, setState] = useState<PharmacyState>("permission")
  const [openOnly, setOpenOnly] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)

  // 데모: 주소에 "없음"/"오류"가 포함되면 해당 상태를 보여준다.
  // 백엔드 GET /api/v1/pharmacies?lat=&lng= 연동 시 교체한다.
  const load = (address = "") => {
    setState("loading")
    setTimeout(
      () => setState(address.includes("없음") ? "empty" : address.includes("오류") ? "error" : "map"),
      700,
    )
  }

  const requestMyLocation = () => {
    if (!navigator.geolocation) {
      setState("denied")
      return
    }
    setState("loading")
    navigator.geolocation.getCurrentPosition(
      () => load(),
      () => setState("denied"),
      { timeout: 8000 },
    )
  }

  return (
    <>
      <h1 className="text-3xl font-bold">내 주변 약국</h1>
      <p className="mt-3 text-slate-500">가까운 약국을 찾고, 방문 전 확인해 보세요.</p>
      {state === "permission" || state === "denied" ? (
        <LocationRequest
          denied={state === "denied"}
          onUseLocation={requestMyLocation}
          onDeny={() => setState("denied")}
          onSearchAddress={load}
          onDemo={() => load()}
        />
      ) : state === "loading" ? (
        <div role="status" className="flex min-h-80 items-center justify-center gap-3 text-slate-500">
          <LoaderCircle className="animate-spin" />
          주변 약국을 찾는 중이에요
        </div>
      ) : state === "empty" || state === "error" ? (
        <div className="py-20 text-center">
          <p>
            {state === "empty"
              ? "주변 약국이 없어요. 다른 주소로 찾아보세요."
              : "약국 정보를 불러오지 못했어요."}
          </p>
          <button onClick={() => setState("denied")} className={`${button} mt-6`}>
            다시 찾기
          </button>
        </div>
      ) : (
        <div className="mt-8 grid grid-cols-[380px_minmax(0,1fr)] gap-6">
          <PharmacyList
            pharmacies={pharmacies}
            openOnly={openOnly}
            onToggleOpenOnly={() => setOpenOnly(!openOnly)}
            onSelect={setSelected}
          />
          <PharmacyMap pharmacies={pharmacies} onSelect={setSelected} />
        </div>
      )}
      {selected !== null && (
        <Modal title={pharmacies[selected].name} close={() => setSelected(null)}>
          <Notice>가상 약국입니다. 실제 전화 및 길찾기는 연결되지 않아요.</Notice>
          <p className="mt-5">{pharmacies[selected].address}</p>
        </Modal>
      )}
    </>
  )
}
