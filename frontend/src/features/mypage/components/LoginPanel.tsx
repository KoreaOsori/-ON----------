import { UserRound } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"

const socialProviders = ["카카오", "네이버", "구글"]

// 데모 로그인. 백엔드 /api/v1/auth/oauth/{provider}/authorize 연동 시 소셜 버튼을 OAuth 리다이렉트로 교체한다.
export default function LoginPanel({
  email,
  setEmail,
  onStart,
}: {
  email: string
  setEmail: (value: string) => void
  onStart: () => void
}) {
  return (
    <div className="mx-auto max-w-md py-8">
      <div className="mb-7 flex h-16 w-16 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
        <UserRound size={30} />
      </div>
      <h1 className="text-3xl font-bold leading-relaxed">
        나를 위한 약 관리,
        <br />
        약온과 함께해요
      </h1>
      <p className="mb-8 mt-4 leading-7 text-slate-500">
        내 복용약과 건강 정보를 바탕으로
        <br />더 편리하게 관리할 수 있어요.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onStart()
        }}
      >
        <label className="mb-2 block text-sm font-medium">이메일</label>
        <input
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="이메일 주소를 입력해 주세요"
          className={inputClass}
        />
        <button className={`${button} mt-4 w-full`}>이메일로 시작하기</button>
      </form>
      <div className="my-6 text-center text-sm text-slate-400">또는 소셜 계정으로 시작하기</div>
      {socialProviders.map((social, index) => (
        <button
          key={social}
          onClick={() => {
            setEmail(`${social} 데모 계정`)
            onStart()
          }}
          className={`mb-3 min-h-12 w-full rounded-xl border text-sm font-medium ${
            index === 0
              ? "border-yellow-200 bg-yellow-50"
              : index === 1
                ? "border-green-100 bg-green-50"
                : "border-slate-200"
          }`}
        >
          {social}로 시작하기 · 데모
        </button>
      ))}
      <Notice>
        실제 가입 없이 로그인 상태를 체험할 수 있어요. 입력한 정보는 서버에 전송되지 않으며 새로고침하면 초기화돼요.
      </Notice>
    </div>
  )
}
