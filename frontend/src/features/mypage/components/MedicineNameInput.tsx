"use client"

import { useEffect, useState } from "react"
import { inputClass } from "@/components/ui/styles"
import { searchMedicines, type MedicineSummary } from "@/features/medicine/api"

/**
 * 복용약 이름 입력. 약정보 검색과 같은 API 로 후보를 보여주고, 고르면 품목기준코드(itemSeq)를 함께 넘긴다.
 * 고르지 않고 직접 쓴 이름도 저장은 되지만 병용 확인에서는 불러올 수 없다 (병용 판정은 품목기준코드 기준)
 */
export default function MedicineNameInput({
  name,
  itemSeq,
  onChange,
  autoFocus,
}: {
  name: string
  itemSeq?: string
  onChange: (name: string, itemSeq?: string) => void
  autoFocus?: boolean
}) {
  const [found, setFound] = useState<MedicineSummary[]>([])

  // 입력이 멈추면 검색한다 (글자마다 요청하지 않음). 이미 고른 뒤에는 찾지 않는다
  useEffect(() => {
    const keyword = name.trim()
    if (!keyword || itemSeq) return
    const timer = setTimeout(() => {
      searchMedicines(keyword)
        .then((items) => setFound(items.slice(0, 5)))
        .catch(() => setFound([]))
    }, 300)
    return () => clearTimeout(timer)
  }, [name, itemSeq])

  const suggestions = name.trim() && !itemSeq ? found : []

  return (
    <div>
      <label className="block text-sm">
        약 이름
        {itemSeq && <span className="ml-2 text-emerald-700">선택됨</span>}
        <input
          autoFocus={autoFocus}
          required
          maxLength={100}
          className={`${inputClass} mt-1`}
          value={name}
          onChange={(event) => onChange(event.target.value)}
          placeholder="약 이름을 검색해 선택해 주세요"
        />
      </label>
      {suggestions.length > 0 && (
        <div className="mt-2 rounded-xl border border-slate-200 bg-white">
          {suggestions.map((medicine) => (
            <button
              key={medicine.id}
              type="button"
              onClick={() => onChange(medicine.name, medicine.id)}
              className="block min-h-11 w-full border-b border-slate-100 px-4 py-2 text-left text-sm last:border-0 hover:bg-blue-50"
            >
              {medicine.name}
              <span className="ml-2 text-slate-500">{medicine.maker}</span>
            </button>
          ))}
        </div>
      )}
      {name.trim() && !itemSeq && (
        <p className="mt-1 text-xs text-slate-500">목록에서 고르면 병용 확인에서 내 복용약으로 불러올 수 있어요.</p>
      )}
    </div>
  )
}
