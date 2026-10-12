import { drugCategories } from "@/mocks/drugs"

export default function CategoryFilter({
  value,
  onChange,
}: {
  value: string
  onChange: (category: string) => void
}) {
  return (
    <div className="my-5 flex flex-wrap gap-2">
      {drugCategories.map((item) => (
        <button
          key={item}
          onClick={() => onChange(item)}
          className={`min-h-11 rounded-full border px-4 text-sm ${
            value === item
              ? "border-blue-600 bg-blue-600 text-white"
              : "border-slate-200 text-slate-600"
          }`}
        >
          {item}
        </button>
      ))}
    </div>
  )
}
