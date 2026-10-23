/* eslint-disable @next/next/no-img-element -- 브라우저 안의 미리보기(blob:) 주소라 next/image 를 쓸 수 없음 */
import { X } from "lucide-react"

// 사진 미리보기 묶음: 입력창 위(첨부 대기, 빼기 버튼 있음)와 보낸 말풍선 안에서 같이 쓴다
export default function PhotoThumbs({
  urls,
  label,
  onRemove,
}: {
  urls: string[]
  /** 사진 종류 표시 (예: 알약 사진) */
  label?: string
  onRemove?: () => void
}) {
  return (
    <div className="mb-2 flex flex-wrap items-end gap-2">
      {urls.map((url, index) => (
        <div key={url} className="relative">
          <img
            src={url}
            alt={`첨부 사진 ${index + 1}`}
            className="h-24 w-24 rounded-xl border border-white/40 bg-white object-cover"
          />
          {urls.length === 2 && (
            <span className="absolute bottom-1 left-1 rounded bg-slate-900/60 px-1.5 text-[11px] text-white">
              {index === 0 ? "앞면" : "뒷면"}
            </span>
          )}
        </div>
      ))}
      {label && <span className="text-xs text-slate-500">{label}</span>}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="첨부한 사진 빼기"
          className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}
