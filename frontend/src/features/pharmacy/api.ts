import { apiFetch } from "@/lib/api/client"

// 국립중앙의료원 약국 정보 (백엔드 /pharmacies 가 공공데이터포털을 호출)
export type PharmacyResult = {
  id: string
  name: string
  address: string
  phone: string | null
  distanceMeters: number
  latitude: number
  longitude: number
  isOpen: boolean
  statusText: string
  todayHours: string | null
}

export type PharmacyDetail = {
  id: string
  name: string
  address: string
  phone: string | null
  latitude: number | null
  longitude: number | null
  hours: { day: string; hours: string | null }[]
  note: string | null
  directions: string | null
}

export type Coordinates = { lat: number; lng: number }

export const findNearbyPharmacies = ({ lat, lng }: Coordinates) =>
  apiFetch<PharmacyResult[]>("/pharmacies", { query: { lat, lng } })

export const getPharmacy = (id: string) => apiFetch<PharmacyDetail>(`/pharmacies/${id}`)
