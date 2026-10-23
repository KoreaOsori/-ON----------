"use client"

import { useEffect, useState } from "react"
import DrugArt from "@/components/ui/DrugArt"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { getHealthFood, type HealthFoodDetail } from "../api"

// 약 상세정보 모달과 같은 구성
export default function HealthFoodDetailModal({
  id,
  index,
  onClose,
}: {
  id: string
  index: number
  onClose: () => void
}) {
  const [item, setItem] = useState<HealthFoodDetail | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    getHealthFood(id)
      .then(setItem)
      .catch(() => setError(true))
  }, [id])

  const sections: [string, string | undefined][] = [
    ["주된 기능성", item?.functionality],
    ["섭취 방법", item?.intakeMethod],
    ["섭취 시 주의사항", item?.precautions],
    ["원재료", item?.rawMaterials],
    ["보관 방법", item?.storage],
    ["유통기한", item?.shelfLife],
  ]

  return (
    <Modal title="건강기능식품 상세정보" close={onClose}>
      {error && <p className="py-10 text-center text-slate-500">제품 정보를 불러오지 못했어요.</p>}
      {!item && !error && <p className="py-10 text-center text-slate-500">불러오는 중…</p>}
      {item && (
        <>
          <div className="mb-6 flex items-center gap-4">
            <DrugArt index={index} />
            <div>
              <h3 className="text-2xl font-bold">{item.name}</h3>
              <p className="mt-1 text-sm text-slate-500">
                {[item.maker, item.form, item.permitDate && `${item.permitDate} 신고`].filter(Boolean).join(" · ")}
              </p>
            </div>
          </div>
          {sections
            .filter(([, content]) => content)
            .map(([label, content]) => (
              <div key={label} className="mb-5">
                <h4 className="mb-2 font-semibold">{label}</h4>
                <p className="max-h-60 overflow-y-auto whitespace-pre-line leading-7 text-slate-500">{content}</p>
              </div>
            ))}
          <p className="mb-4 text-xs text-slate-400">
            출처: {item.source} · 판매 여부는 알 수 없어요 (신고된 제품 기준)
          </p>
        </>
      )}
      <Notice />
    </Modal>
  )
}
