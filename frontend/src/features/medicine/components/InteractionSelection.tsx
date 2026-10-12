import { X } from "lucide-react"
import { MAX_INTERACTION_DRUGS } from "@/lib/constants"
import { drugs } from "@/mocks/drugs"

export const slotLabels = "ABCDE"

export default function InteractionSelection({
  logged,
  selected,
  onLoadMine,
  onRemove,
}: {
  logged: boolean
  selected: number[]
  onLoadMine: () => void
  onRemove: (index: number) => void
}) {
  return (
    <>
      <p className="mb-5 leading-7">
        궁금한 약을 최대 5개까지 담으면 서로 함께 먹어도 되는지 확인해드려요.
      </p>
      {logged && (
        <button onClick={onLoadMine} className="mb-4 min-h-11 text-blue-600">
          내 복용약 불러오기
        </button>
      )}
      <div className="mb-5 flex flex-wrap gap-2">
        {selected.map((index, order) => (
          <span
            key={index}
            className="flex items-center gap-2 rounded-xl bg-blue-50 py-1 pl-3 text-blue-700"
          >
            <b>{slotLabels[order]}</b>
            {drugs[index].name}
            <button
              aria-label={`${drugs[index].name} 삭제`}
              className="flex h-11 w-11 items-center justify-center"
              onClick={() => onRemove(index)}
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
