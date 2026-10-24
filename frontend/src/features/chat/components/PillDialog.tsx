"use client"

import { useState } from "react"
import { LoaderCircle } from "lucide-react"
import DrugArt from "@/components/ui/DrugArt"
import Notice from "@/components/ui/Notice"
import { inputClass } from "@/components/ui/styles"
import {
  choosePillImprint,
  confirmPill,
  errorMessage,
  refinePill,
  rejectPill,
  type PillCandidate,
  type PillStep,
} from "@/features/photo/api"

// 알약 인식 대화 (워커 yakon_pill 흐름 v4): top1 → (아니오) top3 → (목록에 없음) 각인 입력 → 색 선택 → 재촬영 → 종료
// 문장·버튼 이름은 워커 응답(message·buttons)을 그대로 쓴다
export default function PillDialog({
  initial,
  onConfirm,
  onRetake,
}: {
  initial: PillStep
  onConfirm: (drugName: string) => void
  onRetake: (prevSessionId: string) => void
}) {
  const [state, setState] = useState<PillStep>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [imprint, setImprint] = useState("")
  const sid = state.sessionId

  const run = async (action: () => Promise<PillStep>) => {
    setBusy(true)
    setError("")
    try {
      const next = await action()
      setState((previous) => ({ ...previous, ...next, sessionId: sid }))
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }
  const pick = async (candidate: PillCandidate) => {
    setBusy(true)
    try {
      const handoff = await confirmPill(sid, candidate.itemSeq)
      onConfirm(handoff.name)
    } catch (caught) {
      setError(errorMessage(caught))
      setBusy(false)
    }
  }

  const buttons = state.buttons ?? []
  const candidates = state.candidates ?? []

  return (
    <div className="rounded-2xl border p-5">
      <h2 className="text-xl font-bold">
        {state.step === "top1" ? "이 약이 맞나요?" : state.step === "top3" ? "가지고 계신 약을 골라 주세요" : "알약 확인"}
      </h2>
      {state.message && <p className="my-3 text-sm leading-6 text-slate-600">{state.message}</p>}

      {(state.step === "top1" || state.step === "top3") && (
        <div className="space-y-3">
          {candidates.map((drug, index) => (
            <div key={drug.itemSeq} className="flex items-center gap-3 rounded-xl bg-slate-50 p-3">
              {drug.imageUrl ? (
                // 식약처 낱알 공식 사진 (외부 주소라 next/image 대신 img)
                // eslint-disable-next-line @next/next/no-img-element
                <img src={drug.imageUrl} alt={`${drug.name} 사진`} className="h-16 w-16 rounded-lg bg-white object-contain" />
              ) : (
                <DrugArt index={index} />
              )}
              <div className="flex-1">
                <b>{drug.name}</b>
                <p className="text-xs text-slate-500">
                  {drug.company} · 각인 {[drug.printFront, drug.printBack].filter(Boolean).join(" / ") || "없음"}
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    disabled={busy}
                    onClick={() => pick(drug)}
                    className="min-h-11 rounded-lg bg-blue-600 px-3 text-sm text-white disabled:bg-slate-300"
                  >
                    {state.step === "top1" ? (buttons[0] ?? "네") : "이 약이에요"}
                  </button>
                  {state.step === "top1" && (
                    <button
                      disabled={busy}
                      onClick={() => run(() => rejectPill(sid, "top1"))}
                      className="min-h-11 px-2 text-sm text-slate-500"
                    >
                      {buttons[1] ?? "아니오"}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {state.step === "top3" && (
            <button
              disabled={busy}
              onClick={() => run(() => rejectPill(sid, "top3"))}
              className="min-h-11 text-sm text-slate-600 underline"
            >
              {buttons[1] ?? "목록에 없음"}
            </button>
          )}
        </div>
      )}

      {(state.step === "ask_imprint" || state.step === "imprint_input") && (
        <div className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (imprint.trim()) run(() => refinePill(sid, { imprintFront: imprint.trim() }))
            }}
          >
            <input
              className={inputClass}
              placeholder="예: AB 10"
              maxLength={40}
              value={imprint}
              onChange={(event) => setImprint(event.target.value)}
            />
            <button disabled={busy || !imprint.trim()} className="min-h-12 shrink-0 rounded-xl bg-blue-600 px-4 text-white disabled:bg-slate-300">
              찾기
            </button>
          </form>
          <div className="flex flex-wrap gap-2">
            {buttons.slice(1).map((label) => (
              <button
                key={label}
                disabled={busy}
                onClick={() => run(() => choosePillImprint(sid, label))}
                className="min-h-11 rounded-lg border px-3 text-sm"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {state.step === "ask_color" && (
        <div className="flex flex-wrap gap-2">
          {buttons.map((color) => (
            <button
              key={color}
              disabled={busy}
              onClick={() => run(() => refinePill(sid, { color }))}
              className="min-h-11 rounded-lg border px-3 text-sm"
            >
              {color}
            </button>
          ))}
        </div>
      )}

      {(state.step === "retake" || state.step === "quality") && (
        <>
          {state.step === "quality" && (
            <p className="mb-3 text-xs text-slate-500">처방전·약봉투 사진이라면 사진 종류를 바꿔 다시 올려 주세요.</p>
          )}
          <button onClick={() => onRetake(sid)} className="min-h-11 rounded-lg bg-blue-600 px-4 text-sm text-white">
            다시 촬영하기
          </button>
        </>
      )}

      {busy && <LoaderCircle className="mt-3 animate-spin text-blue-600" size={24} />}
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-4 space-y-2">
        {state.caution && <Notice>{state.caution}</Notice>}
        {state.storageNotice && <p className="text-xs text-slate-500">{state.storageNotice}</p>}
        <Notice />
      </div>
    </div>
  )
}
