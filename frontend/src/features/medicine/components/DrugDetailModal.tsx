"use client"

import DrugArt from "@/components/ui/DrugArt"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { button } from "@/components/ui/styles"
import { drugs } from "@/mocks/drugs"

const detailSections = ["효능·효과", "용법·용량", "주의사항", "병용금기 요약"]

export default function DrugDetailModal({
  index,
  onCheckInteraction,
  onClose,
}: {
  index: number
  onCheckInteraction: () => void
  onClose: () => void
}) {
  const drug = drugs[index]
  return (
    <Modal title="약 상세정보" close={onClose}>
      <div className="mb-6 flex items-center gap-4">
        <DrugArt index={index} />
        <div>
          <h3 className="text-2xl font-bold">{drug.name}</h3>
          <p className="mt-1 text-sm text-slate-500">{drug.maker} · 가상 의약품</p>
        </div>
      </div>
      {detailSections.map((label) => (
        <div key={label} className="mb-5">
          <h4 className="mb-2 font-semibold">{label}</h4>
          <p className="leading-7 text-slate-500">
            화면 구성을 위한 예시 정보입니다. 실제 복용 안내는 약사·의사와 상담해 주세요.
          </p>
        </div>
      ))}
      <button onClick={onCheckInteraction} className={`${button} mb-4 w-full`}>
        이 약으로 병용 확인하기
      </button>
      <Notice />
    </Modal>
  )
}
