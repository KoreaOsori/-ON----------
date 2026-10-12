import type { Metadata } from "next"
import PharmacyView from "@/features/pharmacy/components/PharmacyView"

export const metadata: Metadata = { title: "내 주변 약국" }

export default function PharmacyPage() {
  return <PharmacyView />
}
