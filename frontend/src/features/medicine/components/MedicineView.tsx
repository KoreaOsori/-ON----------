"use client"

import { useEffect, useState } from "react"
import { Search } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"
import { MAX_INTERACTION_DRUGS } from "@/lib/constants"
import { searchMedicines, type MedicineSummary, type MedicineType } from "../api"
import CategoryFilter from "./CategoryFilter"
import DrugCard from "./DrugCard"
import DrugDetailModal from "./DrugDetailModal"
import InteractionResult from "./InteractionResult"
import InteractionSelection from "./InteractionSelection"

type Tab = "search" | "interaction"

const tabs: [Tab, string][] = [
  ["search", "약 검색"],
  ["interaction", "병용 확인"],
]

export default function MedicineView() {
  const [tab, setTab] = useState<Tab>("search")
  const [query, setQuery] = useState("")
  const [type, setType] = useState<MedicineType | undefined>()
  const [results, setResults] = useState<MedicineSummary[]>([])
  const [searchError, setSearchError] = useState(false)
  const [detail, setDetail] = useState<{ drug: MedicineSummary; index: number } | null>(null)
  const [selected, setSelected] = useState<MedicineSummary[]>([])
  const [result, setResult] = useState(false)

  // 입력이 멈추면 검색 (글자마다 요청하지 않음)
  useEffect(() => {
    const keyword = query.trim()
    if (!keyword) return
    const timer = setTimeout(() => {
      searchMedicines(keyword, type)
        .then((items) => {
          setResults(items)
          setSearchError(false)
        })
        .catch(() => setSearchError(true))
    }, 300)
    return () => clearTimeout(timer)
  }, [query, type])

  // 검색어를 지우면 이전 결과는 보이지 않게 한다
  const visible = query.trim() ? results : []

  const isSelected = (drug: MedicineSummary) => selected.some((item) => item.id === drug.id)

  const add = (drug: MedicineSummary) => {
    if (selected.length < MAX_INTERACTION_DRUGS && !isSelected(drug)) {
      setSelected([...selected, drug])
      setResult(false)
    }
  }

  const switchTab = (value: Tab) => {
    setTab(value)
    setResult(false)
    setQuery("")
    setType(undefined)
  }

  return (
    <div className="mx-auto max-w-[1120px]">
      <h1 className="text-3xl font-bold">약정보</h1>
      <p className="mt-3 text-slate-500">알고 먹으면, 조금 더 안심할 수 있어요.</p>
      <div className="my-7 flex border-b">
        {tabs.map(([value, label]) => (
          <button
            onClick={() => switchTab(value)}
            key={value}
            className={`min-h-14 flex-1 border-b-2 font-semibold ${
              tab === value ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "interaction" && (
        <InteractionSelection
          selected={selected}
          onRemove={(id) => {
            setSelected(selected.filter((item) => item.id !== id))
            setResult(false)
          }}
        />
      )}
      <div className="relative">
        <Search size={20} className="absolute left-4 top-4 text-slate-400" />
        <input
          className={`${inputClass} pl-12`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="약 이름으로 검색해 보세요"
          aria-label="약 검색"
        />
      </div>
      {tab === "search" && <CategoryFilter value={type} onChange={setType} />}
      <div className="my-6 grid grid-cols-2 gap-4">
        {visible.map((drug, index) => (
          <DrugCard
            key={drug.id}
            drug={drug}
            index={index}
            mode={tab}
            added={isSelected(drug)}
            addDisabled={selected.length >= MAX_INTERACTION_DRUGS || isSelected(drug)}
            onOpen={() => setDetail({ drug, index })}
            onAdd={() => add(drug)}
          />
        ))}
      </div>
      {!visible.length && (
        <div className="py-16 text-center text-slate-500">
          <Search className="mx-auto mb-4" />
          {searchError
            ? "검색하지 못했어요. 잠시 후 다시 시도해 주세요."
            : query.trim()
              ? "검색 결과가 없어요. 다른 이름으로 찾아보세요."
              : "약 이름을 입력해 보세요."}
        </div>
      )}
      {tab === "interaction" && (
        <button
          disabled={selected.length < 2}
          onClick={() => setResult(true)}
          className={`${button} mb-6 w-full`}
        >
          병용 확인하기 ({selected.length}/{MAX_INTERACTION_DRUGS})
        </button>
      )}
      {result && <InteractionResult selected={selected} />}
      <Notice />
      {detail && (
        <DrugDetailModal
          id={detail.drug.id}
          index={detail.index}
          onClose={() => setDetail(null)}
          onCheckInteraction={() => {
            setTab("interaction")
            add(detail.drug)
            setDetail(null)
            setQuery("")
            setType(undefined)
          }}
        />
      )}
    </div>
  )
}
