import { apiFetch } from "@/lib/api/client"

export type MedicineType = "일반" | "전문"

export type MedicineSummary = {
  id: string
  name: string
  maker: string
  category: string
  type: string
  saleStatus: string // 판매 | 판매중지
  imageUrl?: string | null // 식약처 의약품안전나라 제품 사진 (없는 약이 많음)
}

export type DurCaution = {
  type: string // 임부금기 | 특정연령대금기 | 노인주의 | 투여기간주의 | 서방정분할주의
  ingredient: string | null
  grade: string | null
  ageBase: string | null
  maxDosageTerm: string | null
  content: string | null
  remark: string | null
}

export type MedicineDetail = MedicineSummary & {
  efficacy: string
  usage: string
  precautions: string
  interactionSummary: string
  source: string
  durCautions: DurCaution[]
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

export const searchMedicines = (query: string, type?: MedicineType, category?: string) =>
  apiFetch<MedicineSummary[]>("/medicines", { query: { q: query, type, category } })

/** 일반·전문의약품별 하위 분류 (대표 분류 10개 + 기타) */
export const getMedicineCategories = () => apiFetch<Record<MedicineType, string[]>>("/medicines/categories")

export type HealthFoodSummary = {
  id: string
  name: string
  maker: string
  form: string
}

export type HealthFoodDetail = HealthFoodSummary & {
  functionality: string
  intakeMethod: string
  precautions: string
  rawMaterials: string
  storage: string
  shelfLife: string
  permitDate: string | null
  source: string
}

export const searchHealthFoods = (query: string, form?: string) =>
  apiFetch<HealthFoodSummary[]>("/health-foods", { query: { q: query, form } })

export const getHealthFoodForms = () => apiFetch<string[]>("/health-foods/forms")

export const getHealthFood = (id: string) => apiFetch<HealthFoodDetail>(`/health-foods/${id}`)

export const getMedicine = (id: string) => apiFetch<MedicineDetail>(`/medicines/${id}`)

export type MedicineCautions = { name: string; cautions: DurCaution[] }

export const checkInteractions = (medicineIds: string[]) =>
  apiFetch<{
    pairs: InteractionPair[]
    duplicates: DuplicateCaution[]
    medicineCautions: MedicineCautions[]
    notice: string
  }>("/interactions/check", {
    method: "POST",
    body: { medicineIds },
  })
