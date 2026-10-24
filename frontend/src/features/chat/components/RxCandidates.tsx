"use client"

import Notice from "@/components/ui/Notice"
import { needsCheck, rxDrugName, rxFieldText, type RxResult } from "@/features/photo/api"

// 처방전·약봉투 인식 결과 → 약을 골라 챗봇에 질문
export default function RxCandidates({
  result,
  onAsk,
  onRetry,
}: {
  result: RxResult
  onAsk: (drugName: string) => void
  onRetry: () => void
}) {
  return (
    <div className="rounded-2xl border p-5">
      <h2 className="text-xl font-bold">어떤 약이 궁금하세요?</h2>
      <p className="my-3 text-sm text-slate-500">{result.notice}</p>
      {result.drugs.length === 0 ? (
        // 약 이름을 못 찾음 → 사진 종류를 잘못 고른 경우일 수 있음
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          처방전에서 약 이름을 찾지 못했어요. 알약 사진이라면 &quot;알약 사진&quot;으로 다시 올려 주세요.
        </p>
      ) : (
        <div className="space-y-3">
          {result.drugs.map((drug, index) => {
            const name = rxDrugName(drug)
            const dose = rxFieldText(drug.fields.dose)
            const times = rxFieldText(drug.fields.times)
            const days = rxFieldText(drug.fields.days)
            const check = !drug.auto || ["dose", "times", "days"].some((k) => needsCheck(drug.fields[k as "dose"]))
            return (
              <div key={index} className="flex items-center gap-3 rounded-xl bg-slate-50 p-3">
                <div className="flex-1">
                  <b>{name}</b>
                  {!drug.auto && <span className="ml-2 text-xs text-amber-700">{drug.decision}</span>}
                  <p className="text-xs text-slate-500">
                    1회 {dose || "-"} · 하루 {times || "-"}회 · {days || "-"}일{check && " (확인 필요)"}
                  </p>
                </div>
                <button
                  onClick={() => onAsk(name)}
                  className="min-h-11 shrink-0 rounded-lg bg-blue-600 px-3 text-sm text-white"
                >
                  이 약 질문하기
                </button>
              </div>
            )
          })}
        </div>
      )}
      <button className="mt-4 min-h-11 text-sm text-blue-600" onClick={onRetry}>
        다시 사진 첨부하기
      </button>
      <div className="mt-3 space-y-2">
        {result.storage && <p className="text-xs text-slate-500">{result.storage}</p>}
        <Notice />
      </div>
    </div>
  )
}
