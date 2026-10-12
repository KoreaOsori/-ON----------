import { ChevronRight } from "lucide-react"
import DrugArt from "@/components/ui/DrugArt"
import type { Drug } from "@/types/drug"

export default function DrugCard({
  drug,
  index,
  mode,
  added,
  addDisabled,
  onOpen,
  onAdd,
}: {
  drug: Drug
  index: number
  mode: "search" | "interaction"
  added: boolean
  addDisabled: boolean
  onOpen: () => void
  onAdd: () => void
}) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border p-4">
      <DrugArt index={index} />
      <button onClick={onOpen} className="min-h-14 flex-1 text-left">
        <b>{drug.name}</b>
        <p className="mt-1 text-sm text-slate-500">
          {drug.maker}{" "}
          <span className="ml-1 rounded bg-slate-100 px-1.5 text-xs">{drug.type} 의약품</span>
        </p>
      </button>
      {mode === "interaction" ? (
        <button
          disabled={addDisabled}
          onClick={onAdd}
          className="min-h-11 rounded-lg bg-blue-50 px-3 text-sm text-blue-600 disabled:text-slate-400"
        >
          {added ? "추가됨" : "추가"}
        </button>
      ) : (
        <ChevronRight size={18} className="text-slate-400" />
      )}
    </div>
  )
}
