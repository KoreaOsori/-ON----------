"use client"

import { useEffect, useState } from "react"
import DrugArt from "@/components/ui/DrugArt"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { button } from "@/components/ui/styles"
import { useSession } from "@/providers/SessionProvider"
import { getMedicine, type MedicineDetail } from "../api"
import { matchConditions } from "../conditionMatch"
import { matchesProfile } from "../profileMatch"
import MineBadge from "./MineBadge"

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
  const { logged, memberProfile, guestProfile } = useSession()
  const profile = logged ? memberProfile : guestProfile
  const [drug, setDrug] = useState<MedicineDetail | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    getMedicine(id)
      .then(setDrug)
      .catch(() => setError(true))
  }, [id])

  const conditionCautions = drug
    ? [...matchConditions(logged ? memberProfile.conditions : undefined, [drug])]
    : []

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
            <DrugArt index={index} imageUrl={drug.imageUrl} />
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
                    {matchesProfile(caution, profile) === true && <MineBadge />}
                    {caution.content && <span className="block whitespace-pre-line">{caution.content}</span>}
                    {caution.remark && <span className="block text-sm">비고: {caution.remark}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {/* 지병 주의: 회원 건강정보의 지병만 (비회원은 지병을 입력하지 않는다) */}
          {conditionCautions.length > 0 && (
            <div className="mb-5">
              <h4 className="mb-2 font-semibold">내 지병 관련</h4>
              {drug.contraindicatedPatients.length === 0 ? (
                <p className="leading-7 text-amber-700">
                  허가 문서에서 &apos;투여하지 말 것&apos; 항목을 찾지 못해 지병은 확인하지 못했어요.
                </p>
              ) : (
                <ul className="space-y-3">
                  {conditionCautions.map(([condition, found]) => (
                    <li key={condition} className="leading-7 text-slate-500">
                      <span className="font-semibold text-slate-700">{condition}</span>
                      {found.length === 0 && (
                        <span className="block">&apos;투여하지 말 것&apos; 항목에서 찾은 내용이 없어요.</span>
                      )}
                      {found.map((item) => (
                        <span key={item.line} className="block">
                          <span
                            className={`mr-2 rounded-md px-2 py-0.5 text-xs font-semibold ${
                              item.contraindicated ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-700"
                            }`}
                          >
                            {item.contraindicated ? "투여하지 말 것" : "주의"}
                          </span>
                          {item.line}
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs text-slate-400">
                허가 문서 &apos;투여하지 말 것&apos; 항목의 문장으로 찾은 것으로, 판정이 아니에요. 정도(심한·중증 등)가 붙은 경우는
                &apos;주의&apos;로 표시했어요.
              </p>
            </div>
          )}
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
