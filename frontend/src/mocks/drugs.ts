import type { CatalogMedicine, Drug } from "@/types/drug"

// 화면 구성용 가상 데이터. 백엔드 연동 시 /api/v1/medicines 응답으로 교체한다.
export const drugs: Drug[] = [
  {
    name: "가나다정",
    maker: "가상제약",
    category: "해열진통제",
    type: "일반",
    color: "bg-blue-100",
  },
  {
    name: "라마바정",
    maker: "온유제약 (가상)",
    category: "감기약",
    type: "일반",
    color: "bg-green-100",
  },
  {
    name: "사아자정",
    maker: "가상바이오",
    category: "소화제",
    type: "전문",
    color: "bg-orange-100",
  },
  {
    name: "차카타정",
    maker: "가상제약",
    category: "알레르기약",
    type: "전문",
    color: "bg-violet-100",
  },
  {
    name: "마바사정",
    maker: "온유제약 (가상)",
    category: "피부약",
    type: "일반",
    color: "bg-rose-100",
  },
]

// 건강정보 입력 화면에서만 추가로 노출되는 가상 약
export const extraCatalogMedicines: CatalogMedicine[] = [
  { name: "가나정", category: "해열진통제", maker: "데모제약 (가상)" },
  { name: "가다나정", category: "감기약", maker: "데모제약 (가상)" },
]

export const drugCategories = [
  "전체",
  "해열진통제",
  "감기약",
  "소화제",
  "알레르기약",
  "피부약",
  "안약",
]
