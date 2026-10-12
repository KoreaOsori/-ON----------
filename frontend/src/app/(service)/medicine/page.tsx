import type { Metadata } from "next"
import MedicineView from "@/features/medicine/components/MedicineView"

export const metadata: Metadata = { title: "약정보" }

export default function MedicinePage() {
  return <MedicineView />
}
