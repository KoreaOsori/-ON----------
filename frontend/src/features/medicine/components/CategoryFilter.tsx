import type { MedicineType } from "../api"

const options: [MedicineType | undefined, string][] = [
  [undefined, "전체"],
  ["일반", "일반의약품"],
  ["전문", "전문의약품"],
]

export default function CategoryFilter({
  value,
  onChange,
}: {
  value: MedicineType | undefined
  onChange: (type: MedicineType | undefined) => void
}) {
  return (
    <div className="my-5 flex flex-wrap gap-2">
      {options.map(([type, label]) => (
        <button
          key={label}
          onClick={() => onChange(type)}
          className={`min-h-11 rounded-full border px-4 text-sm ${
            value === type
              ? "border-blue-600 bg-blue-600 text-white"
              : "border-slate-200 text-slate-600"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
