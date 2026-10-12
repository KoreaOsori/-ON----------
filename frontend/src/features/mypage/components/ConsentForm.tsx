"use client"

import { useState } from "react"
import Modal from "@/components/ui/Modal"
import { button } from "@/components/ui/styles"

const requiredConsents = [
  "이용약관 (필수)",
  "개인정보 수집·이용 (필수)",
  "건강정보(민감정보) 수집·이용 별도 동의 (필수)",
]

export default function ConsentForm({
  consents,
  setConsents,
  onContinue,
}: {
  consents: boolean[]
  setConsents: (value: boolean[]) => void
  onContinue: () => void
}) {
  const [terms, setTerms] = useState<string | null>(null)
  return (
    <div className="mx-auto max-w-lg">
      <h1 className="text-2xl font-bold">서비스 이용에 동의해 주세요</h1>
      <p className="mt-3 text-slate-500">건강정보는 별도 동의를 받아 사용해요.</p>
      <label className="my-6 flex min-h-14 items-center gap-3 rounded-xl bg-slate-50 p-4">
        <input
          type="checkbox"
          checked={consents.every(Boolean)}
          onChange={(event) => setConsents(consents.map(() => event.target.checked))}
          className="h-5 w-5 accent-blue-600"
        />
        필수 항목 전체 동의
      </label>
      {requiredConsents.map((label, index) => (
        <div key={label} className="flex min-h-20 items-center justify-between gap-3 border-b">
          <label className="flex items-center gap-3 text-sm leading-6">
            <input
              type="checkbox"
              className="h-5 w-5 shrink-0 accent-blue-600"
              checked={consents[index]}
              onChange={(event) =>
                setConsents(
                  consents.map((value, position) =>
                    position === index ? event.target.checked : value,
                  ),
                )
              }
            />
            {label}
          </label>
          <button
            onClick={() => setTerms(label)}
            className="min-h-11 shrink-0 px-3 text-sm text-slate-500 underline"
          >
            보기
          </button>
        </div>
      ))}
      <button
        disabled={!consents.every(Boolean)}
        onClick={onContinue}
        className={`${button} mt-7 w-full`}
      >
        동의하고 계속하기
      </button>
      {terms && (
        <Modal title={terms} close={() => setTerms(null)}>
          <p className="leading-8">
            이 화면은 동의 흐름을 보여주는 데모입니다. 실제 서비스에서는 수집 항목, 목적, 보유 기간, 동의 거부 권리 등이 명시된 약관을 제공해야 합니다.
          </p>
        </Modal>
      )}
    </div>
  )
}
