"use client"

import { useState } from "react"
import { UserRound } from "lucide-react"
import { button, inputClass } from "@/components/ui/styles"

// 이메일(아이디)만 입력하는 간단 로그인. 처음 쓰는 이메일이면 계정을 만들고, 이미 있으면 그 계정의 정보를 불러온다
export default function LoginPanel({ onSubmit }: { onSubmit: (email: string) => Promise<void> }) {
  const [email, setEmail] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
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
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setError("")
          try {
            await onSubmit(email.trim())
          } catch {
            setError("로그인하지 못했어요. 이메일을 확인하고 다시 시도해 주세요.")
          } finally {
            setBusy(false)
          }
        }}
      >
        <label htmlFor="login-email" className="mb-2 block text-sm font-medium">
          이메일
        </label>
        <input
          id="login-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="이메일 주소를 입력해 주세요"
          className={inputClass}
        />
        {error && (
          <p role="alert" className="mt-2 text-sm text-red-600">
            {error}
          </p>
        )}
        <button disabled={busy} className={`${button} mt-4 w-full`}>
          {busy ? "확인하는 중…" : "이메일로 시작하기"}
        </button>
      </form>
      <p className="mt-4 text-xs leading-5 text-slate-500">
        처음 입력한 이메일이면 새 계정을 만들고, 사용한 적 있는 이메일이면 저장된 정보를 불러와요.
      </p>
    </div>
  )
}
