export type ChatMessage = {
  question: string
  answer: string
  drug: string | null
  context: string
}

export type ChatStatus = "idle" | "loading" | "error" | "limit"
