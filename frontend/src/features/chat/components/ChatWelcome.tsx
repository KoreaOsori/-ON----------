import { FileText, MessageCircle, Pill, ShieldCheck } from "lucide-react"

export default function ChatWelcome() {
  return (
    <section className="mx-auto flex max-w-[840px] flex-col items-center pt-[72px] text-center">
      <div className="mb-7 flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3.5 py-1.5 text-xs font-medium text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        나와 가족을 위한 약 정보 도우미
      </div>
      <div className="mb-6 flex h-[76px] w-[76px] items-center justify-center rounded-[25px] bg-blue-50 text-blue-600">
        <Pill size={38} strokeWidth={1.4} />
      </div>
      <h1 className="text-[46px] font-bold leading-[1.4] tracking-[-0.8px]">
        어떤 약이 <span className="text-blue-600">궁금하세요?</span>
      </h1>
      <p className="mt-4 text-[18px] leading-8 text-slate-500">
        복용 방법부터 함께 먹는 약까지, 궁금한 점을 편하게 물어보세요.
      </p>
      <p className="mt-7 text-sm text-slate-500">
        약 이름을 입력해 시작해 보세요. 예: “가나다정에 대해 알려주세요”
      </p>
      <div className="mt-8 flex items-center gap-2 text-xs text-slate-400">
        <ShieldCheck size={14} />
        회원가입 없이 바로 시작할 수 있어요
      </div>
      <div className="mt-12 flex flex-wrap justify-center gap-x-7 gap-y-3 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <FileText size={14} />
          등록 정보 기반 안내
        </span>
        <span className="flex items-center gap-1.5">
          <MessageCircle size={14} />
          쉽고 친절한 설명
        </span>
        <span className="flex items-center gap-1.5">
          <ShieldCheck size={14} />
          개인정보 보호
        </span>
      </div>
    </section>
  )
}
