"use client"

import { useState } from "react"
import { Search } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"
import { MAX_INTERACTION_DRUGS } from "@/lib/constants"
import { drugs } from "@/mocks/drugs"
import { useSession } from "@/providers/SessionProvider"
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
  const { logged } = useSession()
  const [tab, setTab] = useState<Tab>("search")
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("전체")
  const [detail, setDetail] = useState<number | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [result, setResult] = useState(false)

  const filtered = drugs
    .map((drug, index) => ({ drug, index }))
    .filter(
      ({ drug }) =>
        drug.name.includes(query) && (category === "전체" || drug.category === category),
    )

  const add = (index: number) => {
    if (selected.length < MAX_INTERACTION_DRUGS && !selected.includes(index)) {
      setSelected([...selected, index])
      setResult(false)
    }
  }

  const switchTab = (value: Tab) => {
    setTab(value)
    setResult(false)
    setQuery("")
    setCategory("전체")
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
          logged={logged}
          selected={selected}
          onLoadMine={() => setSelected([0, 1])}
          onRemove={(index) => {
            setSelected(selected.filter((item) => item !== index))
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
      {tab === "search" && <CategoryFilter value={category} onChange={setCategory} />}
      <div className="my-6 grid grid-cols-2 gap-4">
        {filtered.map(({ drug, index }) => (
          <DrugCard
            key={drug.name}
            drug={drug}
            index={index}
            mode={tab}
            added={selected.includes(index)}
            addDisabled={selected.length >= MAX_INTERACTION_DRUGS || selected.includes(index)}
            onOpen={() => setDetail(index)}
            onAdd={() => add(index)}
          />
        ))}
      </div>
      {!filtered.length && (
        <div className="py-16 text-center text-slate-500">
          <Search className="mx-auto mb-4" />
          검색 결과가 없어요. 다른 이름으로 찾아보세요.
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
      {detail !== null && (
        <DrugDetailModal
          index={detail}
          onClose={() => setDetail(null)}
          onCheckInteraction={() => {
            setTab("interaction")
            add(detail)
            setDetail(null)
            setQuery("")
            setCategory("전체")
          }}
        />
      )}
    </div>
  )
}
