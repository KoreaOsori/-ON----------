"use client"

import { useState } from "react"
import { GUEST_DAILY_QUESTION_LIMIT, summarizeProfile } from "@/lib/constants"
import { drugs } from "@/mocks/drugs"
import type { HealthProfile } from "@/types/health"
import { buildMockAnswer } from "../mockAnswer"
import type { ChatMessage, ChatStatus } from "../types"

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
  const [remaining, setRemaining] = useState(GUEST_DAILY_QUESTION_LIMIT)

  /** 질문을 전송한다. 전송이 시작되면 true를 반환한다. */
  const send = (question: string, confirmed = false) => {
    if (!question.trim() || status === "loading" || (blocked && !confirmed)) return false
    if (!remaining && !logged) {
      setStatus("limit")
      return false
    }
    setStatus("loading")
    const drug = drugs.find((item) => question.includes(item.name))?.name ?? null
    const context = summarizeProfile(profile)
    setTimeout(() => {
      if (question.includes("오류")) {
        setStatus("error")
        return
      }
      setMessages((previous) => [
        ...previous,
        { question, drug, context, answer: buildMockAnswer(question, drug) },
      ])
      setRemaining((previous) => Math.max(0, previous - 1))
      setStatus("idle")
    }, 1000)
    return true
  }

  const reset = () => {
    setMessages([])
    setStatus("idle")
  }

  return { messages, status, setStatus, remaining, send, reset }
}
