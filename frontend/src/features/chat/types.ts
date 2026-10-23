import type { LlmCandidate, LlmStatus } from "./api"

export type ChatMessage = {
  question: string
  answer: string
  /** 후속 질문 칩에 쓸 대표 제품명 */
  drug: string | null
  /** 답변에 참고한 건강정보 요약 (화면 표시용) */
  context: string
  status: LlmStatus
  emergency: boolean
  sources: string[]
  candidates: LlmCandidate[]
  /** 이 질문과 함께 보낸 제품명 (사진 확인·후보 선택) */
  products: string[]
}

export type ChatStatus = "idle" | "loading" | "error" | "limit"
