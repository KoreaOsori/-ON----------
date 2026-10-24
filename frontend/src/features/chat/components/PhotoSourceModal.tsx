"use client"

import { Camera, ChevronRight } from "lucide-react"
import Modal from "@/components/ui/Modal"
import type { PhotoPurpose } from "@/features/photo/api"
import { cropConsentLines } from "@/features/photo/consent"

// 사진 종류는 사용자가 고른다 → 알약은 각인 OCR+CNN(/pill), 처방전·약봉투는 OCR+LLM(/ocr/prescriptions)
const photoSources: { purpose: PhotoPurpose; label: string; hint: string }[] = [
  { purpose: "pill", label: "알약 사진", hint: "앞면·뒷면 2장을 함께 선택해 주세요 (1장도 가능)" },
  { purpose: "prescription", label: "처방전·약봉투 사진", hint: "약 이름과 복용 방법이 잘 보이게 1장" },
]

export default function PhotoSourceModal({
  saveCrops,
  setSaveCrops,
  onSelect,
  onClose,
}: {
  saveCrops: boolean
  setSaveCrops: (value: boolean) => void
  onSelect: (purpose: PhotoPurpose) => void
  onClose: () => void
}) {
  const [title, ...rest] = cropConsentLines
  return (
    <Modal title="어떤 사진을 첨부할까요?" close={onClose}>
      {photoSources.map((source) => (
        <button
          key={source.purpose}
          onClick={() => onSelect(source.purpose)}
          className="mb-3 flex min-h-16 w-full items-center gap-3 rounded-xl border p-4 text-left"
        >
          <Camera size={23} className="shrink-0 text-blue-600" />
          <span>
            {source.label}
            <span className="block text-xs text-slate-500">{source.hint}</span>
          </span>
          <ChevronRight size={19} className="ml-auto" />
        </button>
      ))}
      <label className="mt-2 flex items-start gap-3 rounded-xl bg-slate-50 p-4 text-sm">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4"
          checked={saveCrops}
          onChange={(event) => setSaveCrops(event.target.checked)}
        />
        <span>
          <b>{title}</b>
          {rest.map((line) => (
            <span key={line} className="mt-1 block text-slate-500">
              {line}
            </span>
          ))}
        </span>
      </label>
    </Modal>
  )
}
