"use client"

import { useEffect, useRef, useState } from "react"
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Info,
  Pill,
  Search,
  UserRound,
  X,
} from "lucide-react"
import { searchMedicines, type MedicineSummary } from "@/features/medicine/api"
import type { HealthProfile } from "@/types/health"

const action =
  "min-h-12 rounded-xl bg-blue-600 px-6 py-3 font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
const field =
  "mt-2 min-h-12 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 focus:border-blue-500"
const statuses = ["약을 선택할게요", "복용 중인 약 없음", "정확히 모르겠어요"]

export default function HealthSetup({
  profile,
  onSave,
  onCancel,
}: {
  profile: HealthProfile
  onSave: (profile: HealthProfile) => void
  onCancel: () => void
}) {
  const [step, setStep] = useState(1)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [step])
  const [draft, setDraft] = useState<HealthProfile>({
    ...profile,
    medicineStatus: profile.medicineStatus || statuses[0],
    medicines: profile.medicines || [],
    medicineItems: profile.medicineItems || [],
  })
  const [query, setQuery] = useState("")
  const [category, setCategory] = useState("전체")
  const [error, setError] = useState("")
  const [found, setFound] = useState<MedicineSummary[]>([])
  const [searchError, setSearchError] = useState(false)

  // 약정보 검색과 같은 API. 입력이 멈추면 검색한다 (글자마다 요청하지 않음)
  useEffect(() => {
    const keyword = query.trim()
    if (!keyword) return
    const timer = setTimeout(() => {
      searchMedicines(keyword)
        .then((items) => {
          setFound(items)
          setSearchError(false)
        })
        .catch(() => setSearchError(true))
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  const visible = query.trim() ? found : []
  const categories = ["전체", ...new Set(visible.map((item) => item.category).filter(Boolean))]
  const results = visible.filter((item) => category === "전체" || item.category === category)
  const selected = draft.medicineItems || []
  const setSelected = (items: MedicineSummary[]) =>
    setDraft((previous) => ({
      ...previous,
      medicineItems: items,
      medicines: items.map((item) => item.name),
    }))
  const update = (key: keyof HealthProfile, value: string) =>
    setDraft((previous) => ({ ...previous, [key]: value }))
  const today = new Date()
  const maxBirth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`

  return (
    <div className="mx-auto max-w-5xl">
      <button
        type="button"
        onClick={onCancel}
        className="mb-6 flex min-h-11 items-center gap-2 text-slate-500"
      >
        <ChevronLeft size={18} />
        {profile.birth ? "마이페이지로 돌아가기" : "이용 동의로 돌아가기"}
      </button>
      <div className="mb-8 flex items-end justify-between gap-4">
        <div>
          <p className="mb-2 font-medium text-blue-600">내 건강정보</p>
          <h1 ref={heading} tabIndex={-1} className="text-3xl font-bold">
            {step === 1
              ? "먼저, 기본정보를 알려주세요"
              : "복용약과 지병을 알려주세요"}
          </h1>
          <p className="mt-3 leading-7 text-slate-500">
            {step === 1
              ? "답변에 참고할 정보를 정확하게 입력해 주세요."
              : "약 이름을 모르더라도 분류로 찾아볼 수 있어요."}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-blue-50 px-4 py-2 font-medium text-blue-700">
          {step} / 2 단계
        </span>
      </div>
      <ol
        aria-label="건강정보 입력 단계"
        className="mb-8 grid grid-cols-2 gap-3"
      >
        {["기본정보", "복용약 · 지병"].map((label, index) => (
          <li
            key={label}
            aria-current={step === index + 1 ? "step" : undefined}
            className={`flex items-center gap-3 rounded-xl border p-4 font-medium ${
              step === index + 1
                ? "border-blue-200 bg-blue-50 text-blue-700"
                : "border-slate-200 text-slate-500"
            }`}
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white">
              {step > index + 1 ? <Check size={16} /> : index + 1}
            </span>
            {label}
          </li>
        ))}
      </ol>
      <div className="grid gap-6 lg:grid-cols-3">
        <form
          className="rounded-2xl border border-slate-200 bg-white p-6 lg:col-span-2 lg:p-8"
          onSubmit={(event) => {
            event.preventDefault()
            if (step === 1) {
              setStep(2)
              return
            }
            if (!draft.conditions?.trim()) {
              setError(
                "지병 정보를 입력해 주세요. 없으면 ‘없음’, 모르면 ‘모름’으로 입력할 수 있어요.",
              )
              return
            }
            if (draft.medicineStatus === statuses[0] && selected.length === 0) {
              setError(
                "약을 하나 이상 선택하거나 ‘복용 중인 약 없음 / 정확히 모르겠어요’를 선택해 주세요.",
              )
              return
            }
            const birthday = new Date(`${draft.birth}T00:00:00`)
            const age =
              today.getFullYear() -
              birthday.getFullYear() -
              (today.getMonth() < birthday.getMonth() ||
              (today.getMonth() === birthday.getMonth() &&
                today.getDate() < birthday.getDate())
                ? 1
                : 0)
            onSave({
              ...draft,
              age: String(age),
              conditions: draft.conditions?.trim(),
            })
          }}
        >
          {step === 1 ? (
            <>
              <h2 className="mb-6 flex items-center gap-2 text-xl font-bold">
                <UserRound size={22} className="text-blue-600" />
                기본 건강정보
              </h2>
              <p className="mb-5 text-sm text-slate-500">
                모든 항목을 입력해 주세요. 임신 여부가 불확실하면 ‘확인 필요’를
                선택해 주세요.
              </p>
              <div className="grid gap-5 sm:grid-cols-2">
                <label className="font-medium">
                  생년월일
                  <input
                    required
                    type="date"
                    value={draft.birth || ""}
                    min="1900-01-01"
                    max={maxBirth}
                    onChange={(event) => update("birth", event.target.value)}
                    className={field}
                  />
                  <span className="mt-2 block text-sm font-normal text-slate-500">
                    생일 기준으로 만 나이를 계산해요.
                  </span>
                </label>
                <label className="font-medium">
                  성별
                  <select
                    required
                    value={draft.gender}
                    onChange={(event) => update("gender", event.target.value)}
                    className={field}
                  >
                    <option value="" disabled>
                      선택해 주세요
                    </option>
                    <option>여성</option>
                    <option>남성</option>
                    <option>기타</option>
                  </select>
                </label>
                <label className="font-medium">
                  키 (cm)
                  <input
                    required
                    type="number"
                    min="20"
                    max="250"
                    step="0.1"
                    value={draft.height || ""}
                    onChange={(event) => update("height", event.target.value)}
                    placeholder="예: 165"
                    className={field}
                  />
                </label>
                <label className="font-medium">
                  몸무게 (kg)
                  <input
                    required
                    type="number"
                    min="1"
                    max="400"
                    step="0.1"
                    value={draft.weight || ""}
                    onChange={(event) => update("weight", event.target.value)}
                    placeholder="예: 60"
                    className={field}
                  />
                </label>
                <label className="font-medium sm:col-span-2">
                  임신 여부
                  <select
                    required
                    value={draft.pregnant}
                    onChange={(event) => update("pregnant", event.target.value)}
                    className={field}
                  >
                    <option value="" disabled>
                      선택해 주세요
                    </option>
                    <option>임신 중</option>
                    <option>임신 아님</option>
                    <option>확인 필요</option>
                  </select>
                </label>
              </div>
            </>
          ) : (
            <>
              <h2 className="mb-3 flex items-center gap-2 text-xl font-bold">
                <Pill size={22} className="text-blue-600" />
                복용 중인 약
              </h2>
              <p className="mb-5 leading-7 text-slate-500">
                검색 후 목록에서 선택하면 등록돼요. 식약처 허가 의약품에서
                찾아요.
              </p>
              <fieldset className="mb-5 space-y-3">
                <legend className="mb-3 font-medium">현재 복용 상태</legend>
                {statuses.map((status) => (
                  <label
                    key={status}
                    className={`flex min-h-12 items-center gap-3 rounded-xl border p-3 ${
                      draft.medicineStatus === status
                        ? "border-blue-200 bg-blue-50"
                        : "border-slate-200"
                    }`}
                  >
                    <input
                      type="radio"
                      name="medicineStatus"
                      value={status}
                      checked={draft.medicineStatus === status}
                      onChange={() => {
                        setDraft((previous) => ({
                          ...previous,
                          medicineStatus: status,
                          medicines:
                            status === statuses[0] ? previous.medicines : [],
                          medicineItems:
                            status === statuses[0] ? previous.medicineItems : [],
                        }))
                        setError("")
                      }}
                      className="h-5 w-5 accent-blue-600"
                    />
                    {status}
                  </label>
                ))}
              </fieldset>
              {draft.medicineStatus === statuses[0] ? (
                <>
                  <label htmlFor="profile-drug-search" className="font-medium">
                    약 이름 검색
                  </label>
                  <div className="relative mt-2">
                    <Search
                      size={20}
                      className="absolute left-4 top-4 text-slate-400"
                    />
                    <input
                      id="profile-drug-search"
                      type="search"
                      value={query}
                      onChange={(event) => {
                        setQuery(event.target.value)
                        setCategory("전체")
                      }}
                      placeholder="예: 타이레놀, 판콜"
                      className={`${field} mt-0 pl-12`}
                    />
                  </div>
                  <p className="mb-3 mt-4 text-sm text-slate-500">
                    결과가 많으면 분류를 선택해 좁혀 보세요.
                  </p>
                  <div
                    className="mb-5 flex flex-wrap gap-2"
                    aria-label="약 분류"
                  >
                    {categories.map((item) => (
                      <button
                        type="button"
                        key={item}
                        aria-pressed={category === item}
                        onClick={() => setCategory(item)}
                        className={`min-h-11 rounded-full border px-4 ${
                          category === item
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-slate-200 text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {item}
                      </button>
                    ))}
                  </div>
                  <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-200">
                    {results.map((item) => {
                      const added = selected.some((medicine) => medicine.id === item.id)
                      return (
                        <button
                          type="button"
                          key={item.id}
                          aria-pressed={added}
                          onClick={() => {
                            setSelected(
                              added
                                ? selected.filter((medicine) => medicine.id !== item.id)
                                : [...selected, item],
                            )
                            setError("")
                          }}
                          className="flex min-h-20 w-full items-center gap-3 border-b border-slate-100 p-4 text-left last:border-0 hover:bg-blue-50"
                        >
                          <span className="rounded-xl bg-blue-50 p-3 text-blue-600">
                            <Pill size={20} />
                          </span>
                          <span className="flex-1">
                            <span className="block font-medium">
                              {item.name}
                            </span>
                            <span className="mt-1 block text-sm text-slate-500">
                              {[item.category, item.maker, item.saleStatus === "판매중지" && "판매중지"]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                          </span>
                          <span
                            className={
                              added ? "text-emerald-700" : "text-blue-600"
                            }
                          >
                            {added ? (
                              <Check aria-label="선택됨" size={20} />
                            ) : (
                              "추가"
                            )}
                          </span>
                        </button>
                      )
                    })}
                    {results.length === 0 && (
                      <p className="p-5 leading-7 text-slate-500">
                        {searchError
                          ? "약을 검색하지 못했어요. 잠시 후 다시 시도해 주세요."
                          : query.trim()
                            ? "일치하는 약이 없어요. 검색어를 줄이거나 다른 분류를 선택해 주세요. 약을 찾을 수 없다면 ‘정확히 모르겠어요’를 선택해 주세요."
                            : "약 이름을 입력하면 목록이 나와요."}
                      </p>
                    )}
                  </div>
                  <div className="my-5 rounded-xl bg-emerald-50 p-4">
                    <p
                      className="mb-3 font-medium text-emerald-800"
                      aria-live="polite"
                    >
                      등록할 약 {selected.length}개
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {selected.map((medicine) => (
                        <button
                          key={medicine.id}
                          type="button"
                          aria-label={`${medicine.name} 삭제`}
                          onClick={() =>
                            setSelected(selected.filter((item) => item.id !== medicine.id))
                          }
                          className="flex min-h-11 items-center gap-2 rounded-full bg-white px-3 text-emerald-800"
                        >
                          {medicine.name}
                          <X size={16} />
                        </button>
                      ))}
                      {!selected.length && (
                        <span className="text-sm text-slate-600">
                          위 목록에서 약을 선택해 주세요.
                        </span>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <p className="mb-6 rounded-xl bg-slate-50 p-4 leading-7 text-slate-600">
                  {draft.medicineStatus === statuses[1]
                    ? "복용 중인 약이 없는 상태로 저장해요."
                    : "복용약을 확인하지 못한 상태로 저장해요. 약 봉투나 처방전을 준비해 약사에게 확인해 주세요."}
                </p>
              )}
              <label className="block font-medium">
                지병
                <textarea
                  required
                  rows={3}
                  maxLength={1000}
                  value={draft.conditions || ""}
                  onChange={(event) => update("conditions", event.target.value)}
                  placeholder="지병을 자유롭게 입력해 주세요. 없으면 ‘없음’, 모르면 ‘모름’으로 입력해 주세요."
                  className={`${field} resize-y`}
                />
              </label>
              <p className="mt-2 text-sm text-slate-500">
                질환 이름이나 설명을 그대로 적을 수 있어요. 진단을 제공하지
                않습니다.
              </p>
              {error && (
                <p role="alert" className="mt-4 text-red-700">
                  {error}
                </p>
              )}
            </>
          )}
          <div className="mt-8 flex items-center justify-between gap-3 border-t border-slate-100 pt-6">
            {step === 2 && (
              <button
                type="button"
                onClick={() => {
                  setStep(1)
                  setError("")
                }}
                className="flex min-h-12 items-center gap-2 rounded-xl border border-slate-200 px-5"
              >
                <ChevronLeft size={18} />
                이전 단계
              </button>
            )}
            <button
              type="submit"
              className={`${action} ml-auto flex items-center gap-2`}
            >
              {step === 1 ? "다음 · 복용약과 지병" : "건강정보 저장하기"}
              <ChevronRight size={18} />
            </button>
          </div>
        </form>
        <aside className="space-y-5">
          <section className="rounded-2xl bg-blue-50 p-6">
            <Info size={24} className="mb-4 text-blue-600" />
            <h2 className="mb-3 text-lg font-bold">입력 전 확인해 주세요</h2>
            <p className="leading-7 text-slate-600">
              입력한 건강정보와 복용약은 내 계정(이메일)에 저장돼서 다른 기기에서도
              같은 이메일로 불러올 수 있어요. 회원 탈퇴하면 모두 삭제돼요.
            </p>
          </section>
          <section className="rounded-2xl border border-slate-200 p-6">
            <h2 className="mb-3 text-lg font-bold">
              약을 모두 등록해야 하나요?
            </h2>
            <p className="leading-7 text-slate-600">
              건강정보에는 복용약 목록을 등록할 수 있어요. 별도 병용 확인은 한
              번에 최대 5개 약을 대상으로 하며, 모든 상호작용을 확인할 수는
              없습니다.
            </p>
          </section>
          <p className="px-2 text-sm leading-7 text-slate-500">
            데이터에 등록된 정보 기준이며 복용 전 약사·의사와 상담하세요.
          </p>
        </aside>
      </div>
    </div>
  )
}
