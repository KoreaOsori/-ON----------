"use client"

import { useRef, useState } from "react"
import { Check, ChevronLeft, FileText, LoaderCircle } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"
import {
  confirmPrescriptionDrug,
  errorMessage,
  needsCheck,
  recognizePrescription,
  rxDrugName,
  uploadPhoto,
  type RxDrug,
  type RxField,
  type RxResult,
} from "@/features/photo/api"
import type { MedicationDraft, OcrStep } from "../types"

const titles: Record<Exclude<OcrStep, 0>, string> = {
  1: "약봉투·처방전을 촬영해 주세요",
  2: "약 정보를 인식하고 있어요",
  3: "인식 결과를 확인해 주세요",
  4: "약 등록이 완료됐어요",
}

/** "1정"·"3" → "1"·"3" (빈칸이면 빈 문자열 — 0 으로 채우지 않음) */
const numberText = (field?: RxField) => {
  if (!field || field.ui === "빈칸" || !field.value) return ""
  return String(field.value).match(/\d+(?:\.\d+)?/)?.[0] ?? ""
}

// 약봉투·처방전 촬영 → 업로드(presign) → 인식(POST /ocr/prescriptions → pill_model 워커) → 확인 → 저장
export default function MedicineRegistration({
  step,
  setStep,
  draft,
  setDraft,
  onSave,
  onDone,
}: {
  step: Exclude<OcrStep, 0>
  setStep: (step: OcrStep) => void
  draft: MedicationDraft
  setDraft: (draft: MedicationDraft) => void
  onSave: () => void
  onDone: () => void
}) {
  const file = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<RxResult | null>(null)
  const [selected, setSelected] = useState(0)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const fill = (drug: RxDrug) =>
    setDraft({
      ...draft,
      name: rxDrugName(drug),
      amount: numberText(drug.fields.dose),
      times: numberText(drug.fields.times),
      days: numberText(drug.fields.days),
      // 예시 데이터의 날짜가 아니라 오늘부터
      start: new Date().toISOString().slice(0, 10),
    })

  const scan = async (photo: File) => {
    setError("")
    setStep(2)
    try {
      const key = await uploadPhoto(photo, "prescription")
      const recognized = await recognizePrescription(key)
      setResult(recognized)
      setSelected(0)
      if (recognized.drugs[0]) fill(recognized.drugs[0])
      else setDraft({ ...draft, name: "", amount: "", times: "", days: "" })
      setStep(3)
    } catch (caught) {
      setError(errorMessage(caught))
      setStep(1)
    }
  }
  // 예시 결과 (사진 없이 화면 체험)
  const demo = () => {
    setResult(null)
    setStep(2)
    setTimeout(() => setStep(3), 1100)
  }
  // 이름 후보를 고르면 그 품목 기준으로 권장 용법 상한 검증(over·reason)이 반영된다
  const chooseName = async (itemSeq: string) => {
    if (!result?.sessionId) return
    setBusy(true)
    try {
      const { drug } = await confirmPrescriptionDrug(result.sessionId, selected, itemSeq)
      const drugs = result.drugs.map((item, index) => (index === selected ? drug : item))
      setResult({ ...result, drugs })
      fill(drug)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const current = result?.drugs[selected]
  const fieldOf: Partial<Record<keyof MedicationDraft, RxField>> = current
    ? { amount: current.fields.dose, times: current.fields.times, days: current.fields.days }
    : {}
  const fields: { key: keyof MedicationDraft; label: string; type: string }[] = [
    { key: "name", label: "약 이름", type: "text" },
    { key: "amount", label: "1회 복용량 (정)", type: "number" },
    { key: "times", label: "하루 횟수", type: "number" },
    { key: "days", label: "복용 일수", type: "number" },
    { key: "start", label: "시작일", type: "date" },
  ]
  // 강조할 칸: 실제 인식이면 ui 가 "미리 채움"이 아닌 칸 + 이름 미확정, 예시면 기존처럼 복용량 칸
  const warn = (key: keyof MedicationDraft, index: number) => {
    if (!result) return index === 1
    if (key === "name") return !!current && !current.auto && !current.confirmed
    return needsCheck(fieldOf[key])
  }
  const invalid =
    !draft.name.trim() || !draft.start || +draft.amount <= 0 || +draft.times <= 0 || +draft.days <= 0

  return (
    <div className="mx-auto max-w-lg">
      <button
        onClick={() => setStep(0)}
        className="mb-5 flex min-h-11 items-center gap-2 text-sm text-slate-500"
      >
        <ChevronLeft size={18} />
        마이페이지로
      </button>
      <div className="mb-5 flex gap-2">
        {[1, 2, 3, 4].map((item) => (
          <span
            key={item}
            className={`h-1.5 flex-1 rounded-full ${item <= step ? "bg-blue-600" : "bg-slate-100"}`}
          />
        ))}
      </div>
      <h1 className="text-2xl font-bold">{titles[step]}</h1>
      {step === 1 ? (
        <>
          <p className="my-4 leading-7 text-slate-500">약 이름과 복용 방법이 잘 보이도록 담아주세요.</p>
          <div className="flex h-60 items-center justify-center rounded-2xl border-2 border-dashed border-blue-200 bg-blue-50">
            <FileText size={64} className="text-blue-300" />
          </div>
          {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
          <input
            type="file"
            ref={file}
            className="hidden"
            accept="image/*"
            onChange={(event) => {
              const photo = event.target.files?.[0]
              if (photo) scan(photo)
              event.target.value = ""
            }}
          />
          <button onClick={() => file.current?.click()} className={`${button} mt-5 w-full`}>
            촬영 / 앨범에서 선택
          </button>
          <button onClick={demo} className="mt-3 min-h-11 w-full text-blue-600">
            예시 처방전으로 체험하기
          </button>
          <p className="mt-3 text-xs text-slate-500">처방전·약봉투 사진과 읽은 글자는 저장되지 않습니다.</p>
        </>
      ) : step === 2 ? (
        <div className="flex min-h-60 flex-col items-center justify-center gap-3 text-sm text-slate-500">
          <LoaderCircle className="animate-spin text-blue-600" size={40} />
          처방전을 읽고 있어요 (최대 1분)
        </div>
      ) : step === 3 ? (
        <div className="mt-6 space-y-4">
          <Notice>
            {result ? result.notice : "실제 사진 인식이 아닌 예시 결과입니다. 내용을 직접 확인하고 저장해 주세요."}
          </Notice>
          {result && result.drugs.length === 0 && (
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
              약 이름을 찾지 못했어요. 직접 입력하거나 다시 촬영해 주세요.
            </p>
          )}
          {result && result.drugs.length > 1 && (
            <div className="flex flex-wrap gap-2">
              {result.drugs.map((drug, index) => (
                <button
                  key={index}
                  onClick={() => {
                    setSelected(index)
                    fill(drug)
                  }}
                  className={`min-h-11 rounded-lg border px-3 text-sm ${index === selected ? "border-blue-600 bg-blue-50 text-blue-700" : ""}`}
                >
                  {rxDrugName(drug)}
                </button>
              ))}
            </div>
          )}
          {current && !current.auto && !current.confirmed && current.candidates.length > 0 && (
            <div className="rounded-xl bg-slate-50 p-3 text-sm">
              <p className="mb-2 text-amber-700">{current.decision} — 맞는 약 이름을 골라 주세요</p>
              <div className="flex flex-wrap gap-2">
                {current.candidates.map((candidate) => (
                  <button
                    key={candidate.itemSeq}
                    disabled={busy}
                    onClick={() => chooseName(candidate.itemSeq)}
                    className="min-h-11 rounded-lg border bg-white px-3"
                  >
                    {candidate.itemName}
                    {candidate.status && <span className="ml-1 text-xs text-red-600">({candidate.status})</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
          {fields.map((field, index) => {
            const flagged = warn(field.key, index)
            const info = fieldOf[field.key]
            return (
              <label key={field.key} className="block text-sm">
                {field.label}
                {flagged && (
                  <span className="ml-2 text-amber-700">
                    {info && info.ui !== "확인 필요" ? info.ui : "확인해 주세요"}
                  </span>
                )}
                <input
                  type={field.type}
                  min="1"
                  className={`${inputClass} mt-2 ${flagged ? "border-amber-400 bg-amber-50" : ""}`}
                  value={draft[field.key]}
                  onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })}
                />
                {info?.over && info.reason && <span className="mt-1 block text-xs text-amber-700">{info.reason}</span>}
              </label>
            )
          })}
          <button disabled={invalid} onClick={onSave} className={`${button} w-full`}>
            확인하고 저장
          </button>
          {result?.storage && <p className="text-xs text-slate-500">{result.storage}</p>}
          <Notice />
        </div>
      ) : (
        <div className="py-10 text-center">
          <Check
            size={50}
            className="mx-auto mb-5 rounded-full bg-emerald-50 p-2 text-emerald-600"
          />
          <p className="mb-6">{draft.name}을 내 복용약에 추가했어요.</p>
          {result && result.drugs.length > 1 && (
            <button
              className="mb-3 min-h-11 w-full rounded-xl border text-blue-600"
              onClick={() => {
                // 같은 처방전의 다음 약으로 넘어가 이어서 등록
                const next = (selected + 1) % result.drugs.length
                setSelected(next)
                fill(result.drugs[next])
                setStep(3)
              }}
            >
              같은 처방전의 다른 약도 등록하기
            </button>
          )}
          <button className={`${button} w-full`} onClick={onDone}>
            복약 알림 설정하기
          </button>
        </div>
      )}
    </div>
  )
}
