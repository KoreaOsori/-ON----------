"use client"

import type { ReactNode } from "react"
import { X } from "lucide-react"

export default function Modal({
  title,
  children,
  close,
}: {
  title: string
  children: ReactNode
  close: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-6 backdrop-blur-sm"
      onClick={close}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-3xl bg-white p-8 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="text-xl font-bold">{title}</h2>
          <button
            onClick={close}
            aria-label="닫기"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-50"
          >
            <X size={21} />
          </button>
        </div>
        {children}
      </section>
    </div>
  )
}
