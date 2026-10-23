"use client"

import { useEffect, useRef, useState } from "react"
import { Check, ChevronLeft, FileText, LoaderCircle } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"
import { searchMedicines, type MedicineSummary } from "@/features/medicine/api"
import type { MedicationDraft, OcrStep } from "../types"

const titles: Record<Exclude<OcrStep, 0>, string> = {
  1: "약봉투·처방전을 촬영해 주세요",
  2: "약 정보를 인식하고 있어요",
  3: "인식 결과를 확인해 주세요",
  4: "약 등록이 완료됐어요",
}

// 약봉투·처방전 촬영 → 인식(OCR) → 확인 → 저장
// 백엔드 연동 시: POST /api/v1/uploads/presign 으로 S3 업로드 → POST /api/v1/ocr/prescriptions (Textract)
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
  const scan = () => {
    setStep(2)
    setTimeout(() => setStep(3), 1100)
  }
  // 약 이름: 약정보 검색과 같은 API 로 찾아 고른다 (고르지 않고 직접 쓴 이름도 저장은 되지만 병용 확인에는 못 불러옴)
  const [found, setFound] = useState<MedicineSummary[]>([])
  useEffect(() => {
    const keyword = draft.name.trim()
    if (!keyword || draft.medicine) return
    const timer = setTimeout(() => {
      searchMedicines(keyword)
        .then((items) => setFound(items.slice(0, 5)))
        .catch(() => setFound([]))
    }, 300)
    return () => clearTimeout(timer)
  }, [draft.name, draft.medicine])
  const suggestions = draft.name.trim() && !draft.medicine ? found : []
  const fields: { key: "amount" | "times" | "days" | "start"; label: string; type: string }[] = [
    { key: "amount", label: "1회 복용량 (정)", type: "number" },
    { key: "times", label: "하루 횟수", type: "number" },
    { key: "days", label: "복용 일수", type: "number" },
    { key: "start", label: "시작일", type: "date" },
  ]
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
          <input
            type="file"
            ref={file}
            className="hidden"
            accept="image/*"
            onChange={(event) => {
              if (event.target.files?.length) scan()
            }}
          />
          <button onClick={() => file.current?.click()} className={`${button} mt-5 w-full`}>
            촬영 / 앨범에서 선택
          </button>
          <button onClick={scan} className="mt-3 min-h-11 w-full text-blue-600">
            예시 처방전으로 체험하기
          </button>
        </>
      ) : step === 2 ? (
        <div className="flex min-h-60 items-center justify-center">
          <LoaderCircle className="animate-spin text-blue-600" size={40} />
        </div>
      ) : step === 3 ? (
        <div className="mt-6 space-y-4">
          <Notice>실제 사진 인식이 아닌 예시 결과입니다. 내용을 직접 확인하고 저장해 주세요.</Notice>
          <label className="block text-sm">
            약 이름
            {draft.medicine && <span className="ml-2 text-emerald-700">선택됨</span>}
            <input
              type="text"
              placeholder="약 이름을 검색해 선택해 주세요"
              className={`${inputClass} mt-2`}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value, medicine: null })}
            />
          </label>
          {suggestions.length > 0 && (
            <div className="rounded-xl border border-slate-200">
              {suggestions.map((medicine) => (
                <button
                  key={medicine.id}
                  type="button"
                  onClick={() => setDraft({ ...draft, name: medicine.name, medicine })}
                  className="block min-h-11 w-full border-b border-slate-100 px-4 py-2 text-left text-sm last:border-0 hover:bg-blue-50"
                >
                  {medicine.name}
                  <span className="ml-2 text-slate-500">{medicine.maker}</span>
                </button>
              ))}
            </div>
          )}
          {fields.map((field, index) => (
            <label key={field.key} className="block text-sm">
              {field.label}
              {index === 0 && <span className="ml-2 text-amber-700">확인해 주세요</span>}
              <input
                type={field.type}
                min="1"
                className={`${inputClass} mt-2 ${index === 0 ? "border-amber-400 bg-amber-50" : ""}`}
                value={draft[field.key]}
                onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })}
              />
            </label>
          ))}
          <button disabled={invalid} onClick={onSave} className={`${button} w-full`}>
            확인하고 저장
          </button>
        </div>
      ) : (
        <div className="py-10 text-center">
          <Check
            size={50}
            className="mx-auto mb-5 rounded-full bg-emerald-50 p-2 text-emerald-600"
          />
          <p className="mb-6">{draft.name}을 내 복용약에 추가했어요.</p>
          <button className={`${button} w-full`} onClick={onDone}>
            복약 알림 설정하기
          </button>
        </div>
      )}
    </div>
  )
}
