"use client"

import { useRef, useState } from "react"
import { ApiError } from "@/lib/api/client"
import { GUEST_DAILY_QUESTION_LIMIT } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"
import { askLlm, type LlmAskResponse } from "../api"
import { buildProfileContext, summarizeForChat } from "../profileContext"
import type { ChatMessage, ChatStatus } from "../types"

/** v3 API 의 products 최대 개수 (병용 확인 한도와 같은 10개) */
export const MAX_CHAT_PRODUCTS = 10

const DEFAULT_ERROR = "정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요."

type SendOptions = {
  /** 사진 인식 후보를 확인한 직후처럼, 막혀 있는 상태에서도 보내야 할 때 */
  confirmed?: boolean
  /** 이 질문과 함께 보낼 제품명 (사진 확인·후보 선택) */
  products?: string[]
}

/** 후속 질문 칩에 쓸 대표 제품명: 함께 보낸 제품이 하나면 그것, 아니면 근거 출처의 첫 제품 */
function mainDrug(products: string[], result: LlmAskResponse): string | null {
  if (products.length === 1) return products[0]
  const source = result.sources.find((item) => !item.includes(" × "))
  return source ? source.split(" · ")[0] : null
}

/** 서버가 보낸 안내 문장(detail)이 있으면 그대로, 없으면 기본 문구 */
function errorText(error: unknown) {
  if (error instanceof ApiError && error.status !== 401 && error.status !== 404) {
    const detail = (error.detail as { detail?: unknown } | undefined)?.detail
    if (typeof detail === "string" && detail.trim()) return detail
  }
  return DEFAULT_ERROR
}

export default function useChat({
  logged,
  profile,
  blocked,
}: {
  logged: boolean
  profile: HealthProfile
  /** 사진 인식 후보 확인 중에는 일반 질문을 막는다 */
  blocked: boolean
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [status, setStatus] = useState<ChatStatus>("idle")
  const [errorMessage, setErrorMessage] = useState("")
  const [remaining, setRemaining] = useState(GUEST_DAILY_QUESTION_LIMIT)
  const [lastRequest, setLastRequest] = useState<{ question: string; products: string[] } | null>(null)
  // 새 대화를 시작한 뒤 이전 질문의 응답이 늦게 오면 버린다
  const generation = useRef(0)

  /** 질문을 전송한다. 전송이 시작되면 true를 반환한다. */
  const send = (question: string, options: SendOptions = {}) => {
    const text = question.trim()
    if (!text || status === "loading" || (blocked && !options.confirmed)) return false
    if (!remaining && !logged) {
      setStatus("limit")
      return false
    }
    const products = (options.products ?? []).slice(0, MAX_CHAT_PRODUCTS)
    const context = summarizeForChat(profile)
    const current = generation.current
    setStatus("loading")
    setErrorMessage("")
    setLastRequest({ question: text, products })

    askLlm({
      question: text,
      products: products.length ? products : undefined,
      profile_context: buildProfileContext(profile),
    })
      .then((result) => {
        if (current !== generation.current) return
        setMessages((previous) => [
          ...previous,
          {
            question: text,
            answer: result.answer,
            drug: mainDrug(products, result),
            context,
            status: result.status,
            emergency: result.emergency,
            sources: result.sources,
            candidates: result.candidates,
            products,
          },
        ])
        setRemaining((previous) => Math.max(0, previous - 1))
        setStatus("idle")
      })
      .catch((error: unknown) => {
        if (current !== generation.current) return
        setErrorMessage(errorText(error))
        setStatus("error")
      })
    return true
  }

  /** 마지막 질문을 같은 제품 목록으로 다시 보낸다 */
  const retry = () =>
    lastRequest ? send(lastRequest.question, { confirmed: true, products: lastRequest.products }) : false

  const reset = () => {
    generation.current += 1
    setMessages([])
    setStatus("idle")
    setErrorMessage("")
    setLastRequest(null)
  }

  return { messages, status, setStatus, errorMessage, remaining, send, retry, reset }
}
