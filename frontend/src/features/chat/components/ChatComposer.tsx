import { ArrowUp, ChevronRight, Info, Pill, Plus, UserRound, X } from "lucide-react"
import { disclaimer } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"
import { summarizeForChat } from "../profileContext"
import PhotoThumbs from "./PhotoThumbs"

export default function ChatComposer({
  docked,
  logged,
  profile,
  remaining,
  text,
  setText,
  disabled,
  sendDisabled,
  products,
  onRemoveProduct,
  attachment,
  onRemoveAttachment,
  onSubmit,
  onOpenProfile,
  onOpenPhoto,
}: {
  /** 대화가 시작되면 화면 하단에 고정 */
  docked: boolean
  logged: boolean
  profile: HealthProfile
  remaining: number
  text: string
  setText: (value: string) => void
  disabled: boolean
  sendDisabled: boolean
  /** 사진에서 확인해 질문과 함께 보낼 제품명 */
  products: string[]
  onRemoveProduct: (name: string) => void
  /** 보내기 전 첨부한 사진 미리보기 (없으면 null) */
  attachment: { urls: string[]; label: string } | null
  onRemoveAttachment: () => void
  onSubmit: () => void
  onOpenProfile: () => void
  onOpenPhoto: () => void
}) {
  const summary = summarizeForChat(profile)
  return (
    <div
      className={`${docked ? "fixed inset-x-0 bottom-0 z-20" : "relative mb-12"} bg-gradient-to-t from-white via-white to-white/95 px-8 pb-6 pt-5`}
    >
      <div className="mx-auto max-w-[840px]">
        <div className="mb-3 flex flex-wrap items-center justify-center gap-2 text-sm">
          {logged ? (
            <span className="text-emerald-700">
              회원 프로필 사용 · {summary || "등록된 건강정보 없음"}
            </span>
          ) : (
            <button
              onClick={onOpenProfile}
              className="flex min-h-11 items-center gap-2 rounded-full border border-slate-200 px-4 text-slate-600 hover:border-blue-300"
            >
              <UserRound size={16} />
              {summary ? `임시 정보 · ${summary}` : "임시 건강정보 설정"}
              <ChevronRight size={15} />
            </button>
          )}
        </div>
        <div className="mb-3 flex items-center justify-center gap-2 text-xs text-slate-500">
          {logged ? (
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">
              내 정보 반영 중
            </span>
          ) : (
            <>
              로그인 없이 이용할 수 있어요
              <span className="text-slate-300">·</span>오늘 남은 질문{" "}
              <b className="text-blue-600">{remaining}회</b>
            </>
          )}
        </div>
        {products.length > 0 && (
          <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="flex items-center gap-1 text-slate-500">
              <Pill size={14} />
              함께 확인할 약
            </span>
            {products.map((name) => (
              <span key={name} className="flex items-center gap-1 rounded-full bg-blue-50 py-1 pl-3 pr-1 text-blue-700">
                {name}
                <button
                  type="button"
                  onClick={() => onRemoveProduct(name)}
                  aria-label={`${name} 빼기`}
                  className="flex h-7 w-7 items-center justify-center rounded-full hover:bg-blue-100"
                >
                  <X size={14} />
                </button>
              </span>
            ))}
          </div>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault()
            onSubmit()
          }}
          className="rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_4px_24px_rgba(30,64,120,0.06)]"
        >
          {attachment && (
            <div className="px-2 pt-2">
              <PhotoThumbs urls={attachment.urls} label={attachment.label} onRemove={onRemoveAttachment} />
            </div>
          )}
          <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenPhoto}
            aria-label="사진 첨부"
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-50"
          >
            <Plus size={25} strokeWidth={1.5} />
          </button>
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            disabled={disabled}
            className="min-w-0 flex-1 py-3 text-base outline-none placeholder:text-slate-400"
            placeholder={
              disabled
                ? "먼저 약을 확인해 주세요"
                : attachment
                  ? "사진과 함께 물어볼 내용을 적어 주세요 (선택)"
                  : "약에 대해 무엇이든 물어보세요"
            }
            aria-label="약에 대한 질문"
          />
          <button
            aria-label="질문 보내기"
            disabled={sendDisabled}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white disabled:bg-blue-100 disabled:text-blue-400"
          >
            <ArrowUp size={22} />
          </button>
          </div>
        </form>
        <p className="mt-3 flex items-start justify-center gap-1.5 text-center text-xs leading-5 text-slate-500">
          <Info size={13} className="mt-1 shrink-0" />
          {disclaimer}
        </p>
      </div>
    </div>
  )
}
