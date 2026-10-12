import { LoaderCircle } from "lucide-react"
import Notice from "@/components/ui/Notice"
import type { ChatStatus } from "../types"

export default function ChatStatusNotice({
  status,
  onRetry,
  onLogin,
}: {
  status: ChatStatus
  onRetry: () => void
  onLogin: () => void
}) {
  if (status === "loading")
    return (
      <div role="status" className="space-y-3 rounded-2xl border p-6">
        <p className="flex items-center gap-2 text-slate-500">
          <LoaderCircle size={18} className="animate-spin" />약 정보를 찾는 중이에요
        </p>
        <div className="h-4 w-4/5 animate-pulse rounded bg-slate-100" />
        <div className="h-4 w-3/5 animate-pulse rounded bg-slate-100" />
      </div>
    )
  if (status === "error")
    return (
      <Notice>
        <p>정보를 불러오지 못했어요.</p>
        <button onClick={onRetry} className="mt-2 min-h-11 font-semibold text-blue-600">
          다시 시도
        </button>
      </Notice>
    )
  if (status === "limit")
    return (
      <Notice>
        <p>오늘의 질문을 모두 사용했어요. 로그인하고 이어서 이용해 주세요.</p>
        <button onClick={onLogin} className="mt-3 min-h-11 font-bold text-blue-600">
          로그인하기
        </button>
      </Notice>
    )
  return null
}
