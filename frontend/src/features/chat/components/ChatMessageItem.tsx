import { ArrowUp, Pill } from "lucide-react"
import Notice from "@/components/ui/Notice"
import type { ChatMessage } from "../types"

const followUpQuestions = [
  "이 약은 언제 먹나요?",
  "함께 먹으면 안 되는 약이 있나요?",
  "임산부나 어린이가 먹어도 되나요?",
]

export default function ChatMessageItem({
  message,
  showFollowUps,
  followUpDisabled,
  onFollowUp,
}: {
  message: ChatMessage
  showFollowUps: boolean
  followUpDisabled: boolean
  onFollowUp: (question: string) => void
}) {
  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-blue-600 px-5 py-3.5 text-white">
          {message.question}
        </div>
      </div>
      {/응급|호흡|심각/.test(message.question) && (
        <div role="alert" className="rounded-xl bg-red-50 p-4 font-medium text-red-700">
          증상이 심하면 즉시 119 또는 가까운 응급실로 가세요
        </div>
      )}
      <div className="flex gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
          <Pill size={20} />
        </span>
        <div className="flex-1 rounded-2xl border border-slate-200 p-5">
          <span className="text-sm font-semibold text-blue-600">약온 · 핵심 요약</span>
          <p className="my-4 leading-8">{message.answer}</p>
          {message.context && (
            <p className="mb-4 text-xs text-slate-500">
              답변 시 참고 정보: {message.context} · 개인 맞춤 안내 UI 데모
            </p>
          )}
          <span className="mb-4 inline-flex rounded-lg bg-slate-100 px-3 py-1.5 text-xs text-slate-600">
            식약처 e약은요 · 출처 UI 예시
          </span>
          <Notice />
          {message.drug && showFollowUps && (
            <div className="mt-5 border-t border-slate-100 pt-4">
              <p className="mb-3 text-sm font-medium text-slate-600">
                {message.drug}에 대해 더 궁금하신가요?
              </p>
              <div className="flex flex-wrap gap-2">
                {followUpQuestions.map((question) => (
                  <button
                    key={question}
                    disabled={followUpDisabled}
                    onClick={() => onFollowUp(`${message.drug}에 대해: ${question}`)}
                    className="min-h-11 rounded-full border border-blue-100 bg-blue-50 px-4 text-sm text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                  >
                    {question}
                    <ArrowUp size={13} className="ml-2 inline" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
