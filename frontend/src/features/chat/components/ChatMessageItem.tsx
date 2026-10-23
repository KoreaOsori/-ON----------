import { ArrowUp, Pill } from "lucide-react"
import Notice from "@/components/ui/Notice"
import type { LlmCandidate, LlmStatus } from "../api"
import type { ChatMessage } from "../types"
import PhotoThumbs from "./PhotoThumbs"

const followUpQuestions = [
  "이 약은 언제 먹나요?",
  "함께 먹으면 안 되는 약이 있나요?",
  "임산부나 어린이가 먹어도 되나요?",
]

const statusLabels: Partial<Record<LlmStatus, string>> = {
  done: "약온 · 핵심 요약",
  needs_clarification: "약온 · 제품 확인이 필요해요",
  no_evidence: "약온 · 등록된 정보에서 찾지 못했어요",
  consult: "약온 · 상담 안내",
  crisis: "약온 · 도움 안내",
}

// v3 답변 끝에 붙는 면책 문구. 이미 있으면 카드 아래 안내 박스를 겹쳐 보여 주지 않는다
const ANSWER_FOOTER_MARK = "진단이나 처방이 아니에요"

/** 후보 버튼 문구: 제품명 (제조사). 이 표기를 그대로 다시 보내면 v3 가 제조사로 제품을 좁힌다 */
export function candidateLabel(candidate: LlmCandidate) {
  return candidate.manufacturer ? `${candidate.product_name} (${candidate.manufacturer})` : candidate.product_name
}

export default function ChatMessageItem({
  message,
  showFollowUps,
  followUpDisabled,
  onFollowUp,
  onPickCandidate,
}: {
  message: ChatMessage
  showFollowUps: boolean
  followUpDisabled: boolean
  onFollowUp: (question: string) => void
  onPickCandidate: (candidate: LlmCandidate) => void
}) {
  const showCandidates = message.status === "needs_clarification" && message.candidates.length > 0
  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-sm bg-blue-600 px-5 py-3.5 text-white">
          {!!message.images?.length && <PhotoThumbs urls={message.images} />}
          {message.question}
          {message.products.length > 0 && (
            <p className="mt-1.5 text-xs text-blue-100">함께 확인한 약: {message.products.join(", ")}</p>
          )}
        </div>
      </div>
      {message.emergency && (
        <div role="alert" className="rounded-xl bg-red-50 p-4 font-medium text-red-700">
          증상이 심하거나 약을 많이 먹었다면 즉시 119 또는 가까운 응급실로 가세요
        </div>
      )}
      <div className="flex gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
          <Pill size={20} />
        </span>
        <div className="min-w-0 flex-1 rounded-2xl border border-slate-200 p-5">
          <span className="text-sm font-semibold text-blue-600">{statusLabels[message.status] ?? "약온"}</span>
          {/* 답변의 줄바꿈(목록·문단)을 그대로 보여 준다 */}
          <p className="my-4 whitespace-pre-line break-words leading-8">{message.answer}</p>
          {showCandidates && (
            <div className="mb-4 space-y-2">
              <p className="text-sm font-medium text-slate-600">해당하는 제품을 누르면 그 제품으로 다시 확인해요</p>
              <div className="flex flex-wrap gap-2">
                {message.candidates.slice(0, 8).map((candidate) => (
                  <button
                    key={candidate.product_key}
                    disabled={followUpDisabled}
                    onClick={() => onPickCandidate(candidate)}
                    className="min-h-11 rounded-xl border border-blue-100 bg-blue-50 px-3 text-left text-sm text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                  >
                    {candidateLabel(candidate)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {message.context && (
            <p className="mb-4 text-xs text-slate-500">답변에 참고한 정보: {message.context}</p>
          )}
          {message.sources.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-1.5">
              {message.sources.slice(0, 4).map((source) => (
                <span key={source} className="inline-flex rounded-lg bg-slate-100 px-3 py-1.5 text-xs text-slate-600">
                  {source}
                </span>
              ))}
            </div>
          )}
          {!message.answer.includes(ANSWER_FOOTER_MARK) && <Notice />}
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
