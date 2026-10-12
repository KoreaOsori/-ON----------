import type { ReactNode } from "react"
import { Info } from "lucide-react"
import { disclaimer } from "@/lib/constants"

export default function Notice({ children = disclaimer }: { children?: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 rounded-xl bg-blue-50 px-4 py-3 text-sm leading-relaxed text-slate-600">
      <Info size={17} className="mt-0.5 shrink-0 text-blue-600" />
      <span>{children}</span>
    </div>
  )
}
