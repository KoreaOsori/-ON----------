"use client"

import { useEffect, useState } from "react"
import Notice from "@/components/ui/Notice"
import { summarizeProfile } from "@/lib/constants"
import { useSession } from "@/providers/SessionProvider"
import { matchesProfile } from "../profileMatch"
import MineBadge from "./MineBadge"
import {
  checkInteractions,
  type DuplicateCaution,
  type InteractionPair,
  type MedicineCautions,
  type MedicineSummary,
} from "../api"
import { slotLabels } from "./InteractionSelection"

// 판정 기준: gold.drug_contraindication (품목 DUR = 금기, 성분 규칙 = 성분 기준 주의). 어떤 경우에도 "안전"이라고 표시하지 않는다.
export default function InteractionResult({ selected }: { selected: MedicineSummary[] }) {
  const { logged, memberProfile, guestProfile } = useSession()
  const profile = logged ? memberProfile : guestProfile
  const profileSummary = summarizeProfile(profile)
  const [pairs, setPairs] = useState<InteractionPair[] | null>(null)
  const [duplicates, setDuplicates] = useState<DuplicateCaution[]>([])
  const [medicineCautions, setMedicineCautions] = useState<MedicineCautions[]>([])
  const [error, setError] = useState(false)

  useEffect(() => {
    checkInteractions(selected.map((drug) => drug.id))
      .then((response) => {
        setPairs(response.pairs)
        setDuplicates(response.duplicates)
        setMedicineCautions(response.medicineCautions)
      })
      .catch(() => setError(true))
  }, [selected])

  if (error) return <p className="mb-6 text-center text-slate-500">병용 정보를 불러오지 못했어요.</p>
  if (!pairs) return <p className="mb-6 text-center text-slate-500">확인하는 중…</p>

  const slot = (name: string) => slotLabels[selected.findIndex((drug) => drug.name === name)]
  const flagged = pairs
    .filter((pair) => pair.contraindicated)
    .sort((a, b) => Number(b.level === "금기") - Number(a.level === "금기"))
  const others = pairs.filter((pair) => !pair.contraindicated)
  // DUR 주의를 유형별로 묶는다 (백엔드가 임부금기 → 특정연령대금기 → 노인주의 … 순서로 준다).
  // 건강정보가 있으면 해당하는 줄을 표시하고, 해당하는 줄이 있는 유형을 앞으로
  const cautionGroups = new Map<string, { text: string; mine: boolean }[]>()
  for (const medicine of medicineCautions) {
    for (const caution of medicine.cautions) {
      const detail = [caution.grade, caution.ageBase, caution.maxDosageTerm, caution.ingredient]
        .filter(Boolean)
        .join(", ")
      const text = detail ? `${medicine.name} (${detail})` : medicine.name
      const lines = cautionGroups.get(caution.type) ?? []
      // 내용만 다른 같은 성분 규칙은 한 줄로
      if (!lines.some((line) => line.text === text))
        cautionGroups.set(caution.type, [...lines, { text, mine: matchesProfile(caution, profile) === true }])
    }
  }
  const sortedCautionGroups = [...cautionGroups].sort(
    ([, a], [, b]) => Number(b.some((line) => line.mine)) - Number(a.some((line) => line.mine)),
  )

  return (
    <section className="mb-6 space-y-4">
      <div
        className={`rounded-2xl p-5 font-semibold ${
          flagged.length ? "bg-amber-50 text-amber-800" : "bg-blue-50 text-blue-700"
        }`}
      >
        {flagged.length
          ? `${selected.length}개 약의 ${pairs.length}개 조합을 확인했어요 · 주의가 필요한 조합 ${flagged.length}개`
          : "등록된 병용금기 정보가 없어요"}
      </div>
      {flagged.map((pair) => (
        <div
          key={`${pair.first}-${pair.second}`}
          className={`space-y-4 rounded-2xl border p-5 ${pair.level === "금기" ? "border-red-200" : "border-amber-200"}`}
        >
          <span
            className={`rounded-md px-2.5 py-1 text-sm font-semibold ${
              pair.level === "금기" ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-700"
            }`}
          >
            {pair.level === "금기" ? "병용금기" : "성분 기준 주의"}
          </span>
          <h3 className="text-lg font-bold">
            {slot(pair.first)} {pair.first} + {slot(pair.second)} {pair.second}
          </h3>
          {pair.level !== "금기" && (
            <p className="text-sm text-slate-600">
              품목 DUR 에는 없으나 성분 기준으로 주의가 필요합니다.
            </p>
          )}
          <div className="rounded-xl bg-slate-100 p-4">
            <b className="text-sm">DUR 등록 내용</b>
            <ul className="mt-2 space-y-3 leading-7 text-slate-600">
              {pair.details.map((detail, order) => (
                <li key={order}>
                  <p className="text-sm text-slate-500">
                    {detail.firstIngredients.join(", ")} + {detail.secondIngredients.join(", ")}
                    {detail.basis === "성분 규칙" && " · 성분 기준"}
                  </p>
                  <p>{detail.content || "금기 내용 없음"}</p>
                  {detail.remark && <p className="text-sm text-slate-500">비고: {detail.remark}</p>}
                </li>
              ))}
            </ul>
          </div>
          {pair.discontinued.length > 0 && (
            <p className="text-sm text-amber-700">
              판매중지 약({pair.discontinued.join(", ")})은 공식 DUR 판정이 없어요.
            </p>
          )}
        </div>
      ))}
      {/* 중복 주의: 병용금기가 아니므로 금지가 아닌 주의로만 표시한다 */}
      {duplicates.length > 0 && (
        <div className="space-y-3 rounded-2xl border border-amber-200 p-5">
          <div>
            <h3 className="font-bold text-amber-800">중복 주의</h3>
            <p className="mt-1 text-sm text-slate-500">병용금기는 아니지만 확인이 필요해요.</p>
          </div>
          {duplicates.map((duplicate) => (
            <div key={`${duplicate.kind}-${duplicate.name}`} className="rounded-xl bg-amber-50 p-4 leading-7">
              <b className="text-amber-800">
                {duplicate.kind} 중복 · {duplicate.name}
              </b>
              <p className="text-sm text-slate-600">
                {duplicate.medicines
                  .map((medicine) =>
                    duplicate.kind === "같은 계열"
                      ? `${medicine.name} (${medicine.ingredients.join(", ")})`
                      : medicine.name,
                  )
                  .join(" · ")}
              </p>
              {duplicate.dailyMax.map((text) => (
                <p key={text} className="text-sm text-slate-700">
                  1일 최대 {text}
                </p>
              ))}
            </div>
          ))}
          <p className="text-xs text-slate-500">먹는 약끼리만 비교해요 · 식약처 DUR 효능군중복 · 용량주의 기준</p>
        </div>
      )}
      {/* 약마다의 DUR 주의: 프로필 없이 모두 보여주고, 해당 여부는 사용자가 확인한다 */}
      {cautionGroups.size > 0 && (
        <div className="space-y-3 rounded-2xl border p-5">
          <div>
            <h3 className="font-bold">복용 대상별 주의</h3>
            <p className="mt-1 text-sm text-slate-500">
              {profileSummary
                ? `내 건강정보(${profileSummary}) 기준으로 해당하는 항목을 표시했어요.`
                : "임신 중이거나 나이에 해당하면 확인이 필요해요. 건강정보를 입력하면 해당 항목을 표시해 드려요."}
            </p>
          </div>
          {sortedCautionGroups.map(([type, lines]) => (
            <div key={type} className="rounded-xl bg-slate-100 p-4 leading-7">
              <b className="text-sm">{type}</b>
              {lines.map((line) => (
                <p key={line.text} className="text-sm text-slate-600">
                  {line.text}
                  {line.mine && <MineBadge />}
                </p>
              ))}
            </div>
          ))}
          <p className="text-xs text-slate-500">식약처 DUR 기준 · 자세한 내용은 약 상세정보에서 볼 수 있어요</p>
        </div>
      )}
      {others.length > 0 && (
        <details className="rounded-xl border p-4">
          <summary className="cursor-pointer leading-7">
            나머지 {others.length}개 조합 · 등록된 병용금기 정보 없음
          </summary>
          <div className="mt-3 space-y-2 text-sm text-slate-500">
            {others.map((pair) => (
              <p key={`${pair.first}-${pair.second}`}>
                {pair.first} + {pair.second} · 등록 정보 없음
                {pair.discontinued.length > 0 &&
                  ` (판매중지 약 ${pair.discontinued.join(", ")} — 공식 DUR 판정 없음)`}
              </p>
            ))}
          </div>
        </details>
      )}
      <Notice>
        3개 이상을 동시에 복용할 때의 복합 상호작용은 확인할 수 없고, 약을 2개씩 비교한 결과만 제공해요.
      </Notice>
    </section>
  )
}
