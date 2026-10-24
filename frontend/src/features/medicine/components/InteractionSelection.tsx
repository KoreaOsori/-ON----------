import { X } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { disclaimer, MAX_INTERACTION_DRUGS } from "@/lib/constants"
import type { MedicineSummary } from "../api"

export const slotLabels = "ABCDE"

export default function InteractionSelection({
  selected,
  onRemove,
  onLoadMine,
}: {
  selected: MedicineSummary[]
  onRemove: (id: string) => void
  /** 마이페이지에 등록한 복용약이 있을 때만 */
  onLoadMine?: () => void
}) {
  return (
    <>
      <p className="mb-3 leading-7">
        궁금한 약을 최대 5개까지 담으면 서로 함께 먹어도 되는지 확인해드려요.
      </p>
      <div className="mb-5">
        <Notice>
          3개 이상을 동시에 복용할 때의 복합 상호작용은 확인할 수 없고, 약을 2개씩 비교한 결과만 제공해요.
          <br />
          {disclaimer}
        </Notice>
      </div>
      {onLoadMine && (
        <button onClick={onLoadMine} className="mb-4 min-h-11 text-blue-600">
          내 복용약 불러오기
        </button>
      )}
      <div className="mb-5 flex flex-wrap gap-2">
        {selected.map((drug, order) => (
          <span
            key={drug.id}
            className="flex items-center gap-2 rounded-xl bg-blue-50 py-1 pl-3 text-blue-700"
          >
            <b>{slotLabels[order]}</b>
            {drug.name}
            <button
              aria-label={`${drug.name} 삭제`}
              className="flex h-11 w-11 items-center justify-center"
              onClick={() => onRemove(drug.id)}
            >
              <X size={16} />
            </button>
          </span>
        ))}
      </div>
      {selected.length === MAX_INTERACTION_DRUGS && (
        <p className="mb-4 text-sm text-amber-700">최대 5개까지 선택할 수 있어요</p>
      )}
    </>
  )
}
