import { apiFetch } from "@/lib/api/client"
import type { HealthProfile } from "@/types/health"

export type ChatRequest = {
  question: string
  profile?: Pick<HealthProfile, "gender" | "age" | "pregnant">
}

export type ChatResponse = {
  answer: string
  drug: string | null
  sources: string[]
  emergency: boolean
  remaining: number | null
}

export const sendChat = (payload: ChatRequest) =>
  apiFetch<ChatResponse>("/chat", { method: "POST", body: payload })
