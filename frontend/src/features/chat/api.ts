import { apiFetch } from "@/lib/api/client"

// 약온 LLM v3 (backend/app/llm/v3). nginx 가 /api/* 를 백엔드로 보내고, 백엔드가 /api/llm/v3 에 v3 앱을 붙인다.
// v3 는 X-API-Key 인증 없이 호출한다.
const LLM_PREFIX = "/api/llm/v3"

export type LlmAskRequest = {
  question: string
  /** 사진(OCR)·후보 선택으로 확인된 제품명 목록 (최대 8개) */
  products?: string[]
  /** 성별·나이·임신 여부·복용 중인 약 (최대 1000자). 모델에는 데이터로만 전달된다 */
  profile_context?: string
}

/** done=근거 있는 답변, no_evidence=근거 없음, needs_clarification=제품 확인 필요, consult=복용 중단·감량 상담 안내, crisis=위기 안내 */
export type LlmStatus =
  | "done"
  | "no_evidence"
  | "needs_clarification"
  | "consult"
  | "crisis"
  | "empty"
  | "refusal"
  | "budget"

export type LlmCandidate = {
  product_key: string
  product_name: string
  manufacturer?: string | null
}

export type LlmAskResponse = {
  status: LlmStatus
  answer: string
  grounded: boolean
  emergency: boolean
  sources: string[]
  candidates: LlmCandidate[]
  tools_used: string[]
  rounds: number
  usage: {
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
  }
  latency_ms: number
  model_id: string
}

export const askLlm = (payload: LlmAskRequest) =>
  apiFetch<LlmAskResponse>("/ask", { method: "POST", body: payload, prefix: LLM_PREFIX })
