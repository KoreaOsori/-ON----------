import { apiFetch } from "@/lib/api/client"

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
}

export const findNearbyPharmacies = (params: { lat: number; lng: number; openOnly?: boolean }) =>
  apiFetch<PharmacyResult[]>("/pharmacies", { query: params })

export const findPharmaciesByAddress = (address: string, openOnly?: boolean) =>
  apiFetch<PharmacyResult[]>("/pharmacies", { query: { address, openOnly } })
