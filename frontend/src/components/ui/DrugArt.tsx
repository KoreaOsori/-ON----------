import { Pill } from "lucide-react"
import { drugs } from "@/mocks/drugs"

export default function DrugArt({ index = 0 }: { index?: number }) {
  return (
    <div
      className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl ${drugs[index].color}`}
    >
      <Pill size={30} className="text-slate-600" strokeWidth={1.3} />
    </div>
  )
}
