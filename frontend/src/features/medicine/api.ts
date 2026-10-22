import { apiFetch } from "@/lib/api/client"

export type MedicineType = "일반" | "전문"

export type MedicineSummary = {
  id: string
  name: string
  maker: string
  category: string
  type: string
  saleStatus: string // 판매 | 판매중지
}

export type MedicineDetail = MedicineSummary & {
  efficacy: string
  usage: string
  precautions: string
  interactionSummary: string
  source: string
}

export type ContraindicationDetail = {
  basis: string // 품목 DUR | 성분 규칙
  firstIngredients: string[]
  secondIngredients: string[]
  content: string | null
  remark: string | null
}

export type InteractionPair = {
  first: string
  second: string
  contraindicated: boolean
  level: string | null // 금기 | 성분 기준 주의
  details: ContraindicationDetail[]
  discontinued: string[]
  easyExplanation: string | null
}

export type DuplicateCaution = {
  kind: string // 같은 성분 | 같은 계열
  name: string
  medicines: { name: string; ingredients: string[] }[]
  dailyMax: string[]
}

export const searchMedicines = (query: string, type?: MedicineType) =>
  apiFetch<MedicineSummary[]>("/medicines", { query: { q: query, type } })

export const getMedicine = (id: string) => apiFetch<MedicineDetail>(`/medicines/${id}`)

export const checkInteractions = (medicineIds: string[]) =>
  apiFetch<{ pairs: InteractionPair[]; duplicates: DuplicateCaution[]; notice: string }>("/interactions/check", {
    method: "POST",
    body: { medicineIds },
  })
