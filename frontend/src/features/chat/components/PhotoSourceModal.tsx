"use client"

import { Camera, ChevronRight } from "lucide-react"
import Modal from "@/components/ui/Modal"

const photoSources = ["알약 사진", "처방전·약봉투 사진"]

export default function PhotoSourceModal({
  onSelect,
  onClose,
}: {
  onSelect: (photoType: string) => void
  onClose: () => void
}) {
  return (
    <Modal title="어떤 사진을 첨부할까요?" close={onClose}>
      <p className="mb-4 text-sm text-slate-500">사진 업로드는 인식 화면을 체험하는 데모예요.</p>
      {photoSources.map((label) => (
        <button
          key={label}
          onClick={() => onSelect(label)}
          className="mb-3 flex min-h-16 w-full items-center gap-3 rounded-xl border p-4 text-left"
        >
          <Camera size={23} className="text-blue-600" />
          {label}
          <ChevronRight size={19} className="ml-auto" />
        </button>
      ))}
    </Modal>
  )
}
