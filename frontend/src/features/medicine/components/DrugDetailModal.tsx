"use client"

import { useEffect, useState } from "react"
import DrugArt from "@/components/ui/DrugArt"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { button } from "@/components/ui/styles"
import { getMedicine, type MedicineDetail } from "../api"

export default function DrugDetailModal({
  id,
  index,
  onCheckInteraction,
  onClose,
}: {
  id: string
  index: number
  onCheckInteraction: () => void
  onClose: () => void
}) {
  const [drug, setDrug] = useState<MedicineDetail | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    getMedicine(id)
      .then(setDrug)
      .catch(() => setError(true))
  }, [id])

  const sections: [string, string | undefined][] = [
    ["효능·효과", drug?.efficacy],
    ["용법·용량", drug?.usage],
    ["주의사항", drug?.precautions],
    ["상호작용", drug?.interactionSummary],
  ]

  return (
    <Modal title="약 상세정보" close={onClose}>
      {error && <p className="py-10 text-center text-slate-500">약 정보를 불러오지 못했어요.</p>}
      {!drug && !error && <p className="py-10 text-center text-slate-500">불러오는 중…</p>}
      {drug && (
        <>
          <div className="mb-6 flex items-center gap-4">
            <DrugArt index={index} />
            <div>
              <h3 className="text-2xl font-bold">{drug.name}</h3>
              <p className="mt-1 text-sm text-slate-500">
                {drug.maker} · {drug.type}의약품 · {drug.category || "분류 없음"}
                {drug.saleStatus === "판매중지" && " · 판매중지"}
              </p>
            </div>
          </div>
          {sections
            .filter(([, content]) => content)
            .map(([label, content]) => (
              <div key={label} className="mb-5">
                <h4 className="mb-2 font-semibold">{label}</h4>
                <p className="max-h-60 overflow-y-auto whitespace-pre-line leading-7 text-slate-500">
                  {content}
                </p>
              </div>
            ))}
          <div className="mb-5">
            <h4 className="mb-2 font-semibold">DUR 주의</h4>
            {drug.durCautions.length === 0 ? (
              <p className="leading-7 text-slate-500">
                식약처 DUR에 등록된 임부·연령·노인 등의 주의가 없어요. 안전하다는 뜻은 아니에요.
              </p>
            ) : (
              <ul className="max-h-60 space-y-3 overflow-y-auto">
                {drug.durCautions.map((caution, i) => (
                  <li key={i} className="leading-7 text-slate-500">
                    <span className="font-semibold text-slate-700">
                      {[caution.type, caution.grade, caution.ageBase, caution.maxDosageTerm]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    {caution.ingredient && ` (${caution.ingredient})`}
                    {caution.content && <span className="block whitespace-pre-line">{caution.content}</span>}
                    {caution.remark && <span className="block text-sm">비고: {caution.remark}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <p className="mb-4 text-xs text-slate-400">출처: {drug.source}</p>
          <button onClick={onCheckInteraction} className={`${button} mb-4 w-full`}>
            이 약으로 병용 확인하기
          </button>
        </>
      )}
      <Notice />
    </Modal>
  )
}
