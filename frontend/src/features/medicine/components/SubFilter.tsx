// 하위 분류 버튼 (의약품 분류, 건강기능식품 제형). 위 단계 필터(CategoryFilter)와 구분되게 선택 색을 옅게 한다
export default function SubFilter({
  options,
  value,
  onChange,
  label,
}: {
  options: string[]
  value: string | undefined
  onChange: (value: string | undefined) => void
  label: string
}) {
  return (
    <div className="mb-5 flex flex-wrap gap-2" aria-label={label}>
      {[undefined, ...options].map((option) => (
        <button
          key={option ?? "전체"}
          aria-pressed={value === option}
          onClick={() => onChange(option)}
          className={`min-h-11 rounded-full border px-4 text-sm ${
            value === option
              ? "border-blue-200 bg-blue-50 font-medium text-blue-700"
              : "border-slate-200 text-slate-600"
          }`}
        >
          {option ?? "전체"}
        </button>
      ))}
    </div>
  )
}
