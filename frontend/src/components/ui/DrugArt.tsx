import { Pill } from "lucide-react"

const colors = ["bg-blue-100", "bg-green-100", "bg-orange-100", "bg-violet-100", "bg-rose-100"]

export default function DrugArt({ index = 0 }: { index?: number }) {
  return (
    <div
      className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl ${colors[index % colors.length]}`}
    >
      <Pill size={30} className="text-slate-600" strokeWidth={1.3} />
    </div>
  )
}
