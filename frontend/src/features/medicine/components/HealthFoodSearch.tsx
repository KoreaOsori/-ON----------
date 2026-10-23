"use client"

import { useEffect, useState } from "react"
import { ChevronRight, Search } from "lucide-react"
import DrugArt from "@/components/ui/DrugArt"
import { inputClass } from "@/components/ui/styles"
import { getHealthFoodForms, searchHealthFoods, type HealthFoodSummary } from "../api"
import HealthFoodDetailModal from "./HealthFoodDetailModal"
import SubFilter from "./SubFilter"

// 건강기능식품 검색 (gold.health_food). 약 검색 탭과 같은 화면 구성: 이름 검색 + 제형 분류
export default function HealthFoodSearch() {
  const [query, setQuery] = useState("")
  const [form, setForm] = useState<string | undefined>()
  const [forms, setForms] = useState<string[]>([])
  const [results, setResults] = useState<HealthFoodSummary[]>([])
  const [searchError, setSearchError] = useState(false)
  const [detail, setDetail] = useState<{ id: string; index: number } | null>(null)

  useEffect(() => {
    getHealthFoodForms()
      .then(setForms)
      .catch(() => setForms([])) // 제형 목록을 못 받으면 이름 검색만
  }, [])

  // 입력이 멈추면 검색. 제형을 고르면 검색어 없이도 그 제형의 제품을 보여준다
  useEffect(() => {
    const keyword = query.trim()
    if (!keyword && !form) return
    const timer = setTimeout(() => {
      searchHealthFoods(keyword, form)
        .then((items) => {
          setResults(items)
          setSearchError(false)
        })
        .catch(() => setSearchError(true))
    }, 300)
    return () => clearTimeout(timer)
  }, [query, form])

  const visible = query.trim() || form ? results : []

  return (
    <>
      <div className="relative">
        <Search size={20} className="absolute left-4 top-4 text-slate-400" />
        <input
          className={`${inputClass} pl-12`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="제품 이름으로 검색해 보세요"
          aria-label="건강기능식품 검색"
        />
      </div>
      <div className="mt-5">
        {forms.length > 0 && <SubFilter label="제형" options={forms} value={form} onChange={setForm} />}
      </div>
      <div className="my-6 grid grid-cols-2 gap-4">
        {visible.map((item, index) => (
          <div key={item.id} className="flex items-center gap-4 rounded-2xl border p-4">
            <DrugArt index={index} />
            <button onClick={() => setDetail({ id: item.id, index })} className="min-h-14 flex-1 text-left">
              <b>{item.name}</b>
              <p className="mt-1 text-sm text-slate-500">
                {item.maker}{" "}
                {item.form && <span className="ml-1 rounded bg-slate-100 px-1.5 text-xs">{item.form}</span>}
              </p>
            </button>
            <ChevronRight size={18} className="text-slate-400" />
          </div>
        ))}
      </div>
      {!visible.length && (
        <div className="py-16 text-center text-slate-500">
          <Search className="mx-auto mb-4" />
          {searchError
            ? "검색하지 못했어요. 잠시 후 다시 시도해 주세요."
            : query.trim() || form
              ? "검색 결과가 없어요. 다른 이름으로 찾아보세요."
              : "제품 이름을 입력하거나 제형을 골라 보세요."}
        </div>
      )}
      {detail && <HealthFoodDetailModal id={detail.id} index={detail.index} onClose={() => setDetail(null)} />}
    </>
  )
}
