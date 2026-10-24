"use client"

import { useState } from "react"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"
import { button, inputClass } from "@/components/ui/styles"
import { emptyProfile } from "@/lib/constants"
import type { HealthProfile } from "@/types/health"

export default function GuestProfileModal({
  profile,
  consent,
  setConsent,
  onApply,
  onClose,
}: {
  profile: HealthProfile
  consent: boolean
  setConsent: (value: boolean) => void
  onApply: (profile: HealthProfile) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState(profile)
  return (
    <Modal title="임시 건강정보 설정" close={onClose}>
      <p className="mb-5 leading-7 text-slate-500">
        선택 사항이에요. 답변에 참고할 정보를 설정해 주세요. 로그인하면 임시 정보 대신 회원 프로필을 사용해요.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onApply(draft)
        }}
        className="space-y-5"
      >
        <label className="block">
          성별
          <select
            value={draft.gender}
            onChange={(event) => setDraft({ ...draft, gender: event.target.value })}
            className={`${inputClass} mt-2`}
          >
            <option value="">선택하지 않음</option>
            <option>여성</option>
            <option>남성</option>
            <option>기타</option>
          </select>
        </label>
        <label className="block">
          나이 (만 나이)
          <input
            type="number"
            min="0"
            max="120"
            value={draft.age}
            onChange={(event) => setDraft({ ...draft, age: event.target.value })}
            className={`${inputClass} mt-2`}
            placeholder="예: 35"
          />
        </label>
        <label className="block">
          임신 여부
          <select
            value={draft.pregnant}
            onChange={(event) => setDraft({ ...draft, pregnant: event.target.value })}
            className={`${inputClass} mt-2`}
          >
            <option value="">선택하지 않음</option>
            <option>임신 중</option>
            <option>임신 아님</option>
            <option>확인 필요</option>
          </select>
        </label>
        {/* 질문할 때 LLM v3 의 profile_context 로 함께 보낸다(서버는 저장하지 않음) */}
        <Notice>
          질문할 때 답변을 만드는 데에만 함께 보내고 저장하지 않아요. 새로고침하면 초기화돼요. 실제 의료 판단은 제공하지 않습니다.
        </Notice>
        <label className="flex items-start gap-3 text-sm leading-6">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-1 h-5 w-5 shrink-0 accent-blue-600"
          />
          입력한 건강정보를 챗봇 답변 참고용으로 사용하는 데 동의합니다.
        </label>
        <button disabled={!consent} className={`${button} w-full`}>
          적용하기
        </button>
        <button
          type="button"
          onClick={() => {
            setDraft(emptyProfile)
            setConsent(false)
            onApply(emptyProfile)
          }}
          className="min-h-11 w-full text-slate-500"
        >
          임시 정보 삭제
        </button>
      </form>
    </Modal>
  )
}
