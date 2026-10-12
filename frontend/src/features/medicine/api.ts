import { apiFetch } from "@/lib/api/client"

export type MedicineSummary = {
  id: string
  name: string
  maker: string
  category: string
  type: string
}

export type MedicineDetail = MedicineSummary & {
  efficacy: string
  usage: string
  precautions: string
  interactionSummary: string
}

export type InteractionPair = {
  first: string
  second: string
  contraindicated: boolean
  durContent: string | null
  easyExplanation: string | null
}

export const searchMedicines = (query: string, category?: string) =>
  apiFetch<MedicineSummary[]>("/medicines", { query: { q: query, category } })

export const getMedicine = (id: string) => apiFetch<MedicineDetail>(`/medicines/${id}`)

export const checkInteractions = (medicineIds: string[]) =>
  apiFetch<{ pairs: InteractionPair[] }>("/interactions/check", {
    method: "POST",
    body: { medicineIds },
  })
