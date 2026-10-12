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
        {/* TODO(백엔드 연동): POST /api/v1/chat 은 임시 건강정보를 요청 본문으로 서버에 보낸다(저장은 안 함).
            연동 시 "서버에 전송하지 않아요" → "답변 생성에만 사용하고 저장하지 않아요" 등으로 문구 수정 필요. */}
        <Notice>
          현재 세션에서만 사용하며 서버에 전송하지 않아요. 새로고침하면 초기화돼요. 실제 의료 판단은 제공하지 않습니다.
        </Notice>
        <label className="flex items-start gap-3 text-sm leading-6">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
            className="mt-1 h-5 w-5 shrink-0 accent-blue-600"
          />
          입력한 건강정보를 이 데모의 답변 참고용으로 사용하는 데 동의합니다.
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
