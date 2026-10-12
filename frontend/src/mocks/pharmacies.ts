import type { Pharmacy } from "@/types/pharmacy"

// 화면 구성용 가상 데이터. 백엔드 연동 시 /api/v1/pharmacies 응답으로 교체한다.
export const pharmacies: Pharmacy[] = [
  {
    name: "온마음약국",
    distance: "250m",
    address: "가상시 온유로 24",
    status: "영업 중 · 22:00까지",
  },
  {
    name: "푸른약국",
    distance: "480m",
    address: "가상시 온유로 68",
    status: "영업 종료",
  },
  {
    name: "하루약국",
    distance: "720m",
    address: "가상시 안심길 12",
    status: "오늘 휴무",
  },
]
