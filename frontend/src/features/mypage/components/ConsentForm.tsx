"use client"

import { useState } from "react"
import Modal from "@/components/ui/Modal"
import { button } from "@/components/ui/styles"

const requiredConsents = [
  "이용약관 (필수)",
  "개인정보 수집·이용 (필수)",
  "건강정보(민감정보) 수집·이용 별도 동의 (필수)",
]

// 약관 요약 (실제로 저장하는 항목·보관 방식 기준)
const consentDetails: Record<string, string> = {
  [requiredConsents[0]]:
    "약온은 약 정보 검색, 병용 확인, 주변 약국 찾기, 복용약 관리 기능을 제공합니다. 제공하는 정보는 참고용이며 진단이나 처방을 대신하지 않습니다. 복용 전에는 약사·의사와 상담하세요.",
  [requiredConsents[1]]:
    "수집 항목: 이메일(아이디). 목적: 계정 식별과 내 정보 불러오기. 보유 기간: 회원 탈퇴 시 즉시 삭제. 동의하지 않으면 회원 기능을 쓸 수 없지만, 비회원으로 챗봇·약 정보는 이용할 수 있습니다.",
  [requiredConsents[2]]:
    "수집 항목: 생년월일, 성별, 키, 몸무게, 임신 여부, 복용약, 지병, 복약 체크 기록. 목적: 맞춤 약 정보 안내와 복용약 관리. 보유 기간: 회원 탈퇴 시 즉시 삭제 (설정 > 데이터 삭제로 복용약·복약 기록만 지울 수도 있음). 동의하지 않으면 건강정보를 저장할 수 없습니다.",
}

export default function ConsentForm({
  consents,
  setConsents,
  onContinue,
}: {
  consents: boolean[]
  setConsents: (value: boolean[]) => void
  onContinue: () => void
}) {
  const [terms, setTerms] = useState<string | null>(null)
  return (
    <div className="mx-auto max-w-lg">
      <h1 className="text-2xl font-bold">서비스 이용에 동의해 주세요</h1>
      <p className="mt-3 text-slate-500">건강정보는 별도 동의를 받아 사용해요.</p>
      <label className="my-6 flex min-h-14 items-center gap-3 rounded-xl bg-slate-50 p-4">
        <input
          type="checkbox"
          checked={consents.every(Boolean)}
          onChange={(event) => setConsents(consents.map(() => event.target.checked))}
          className="h-5 w-5 accent-blue-600"
        />
        필수 항목 전체 동의
      </label>
      {requiredConsents.map((label, index) => (
        <div key={label} className="flex min-h-20 items-center justify-between gap-3 border-b">
          <label className="flex items-center gap-3 text-sm leading-6">
            <input
              type="checkbox"
              className="h-5 w-5 shrink-0 accent-blue-600"
              checked={consents[index]}
              onChange={(event) =>
                setConsents(
                  consents.map((value, position) =>
                    position === index ? event.target.checked : value,
                  ),
                )
              }
            />
            {label}
          </label>
          <button
            onClick={() => setTerms(label)}
            className="min-h-11 shrink-0 px-3 text-sm text-slate-500 underline"
          >
            보기
          </button>
        </div>
      ))}
      <button
        disabled={!consents.every(Boolean)}
        onClick={onContinue}
        className={`${button} mt-7 w-full`}
      >
        동의하고 계속하기
      </button>
      {terms && (
        <Modal title={terms} close={() => setTerms(null)}>
          <p className="leading-8">{consentDetails[terms]}</p>
        </Modal>
      )}
    </div>
  )
}
