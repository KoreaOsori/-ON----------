"use client"

import { useState } from "react"
import { Pill } from "lucide-react"

const colors = ["bg-blue-100", "bg-green-100", "bg-orange-100", "bg-violet-100", "bg-rose-100"]

// 약 사진이 있으면 사진(식약처 의약품안전나라 주소를 그대로 씀), 없거나 불러오지 못하면 아이콘
export default function DrugArt({ index = 0, imageUrl }: { index?: number; imageUrl?: string | null }) {
  const [failed, setFailed] = useState(false)
  if (imageUrl && !failed)
    return (
      // eslint-disable-next-line @next/next/no-img-element -- 외부(식약처) 이미지라 최적화 서버를 거치지 않는다
      <img
        src={imageUrl}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        // 식약처 사진은 가로로 긴 낱알 사진(약 1.8:1)이라 정사각형에 넣으면 잘리거나 작아진다 → 같은 높이로 가로만 넓힘
        className="h-16 w-28 shrink-0 rounded-2xl border bg-white object-contain"
      />
    )
  return (
    <div
      className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl ${colors[index % colors.length]}`}
    >
      <Pill size={30} className="text-slate-600" strokeWidth={1.3} />
    </div>
  )
}
