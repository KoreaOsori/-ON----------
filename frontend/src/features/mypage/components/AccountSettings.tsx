"use client"

import { useState } from "react"
import { ChevronRight } from "lucide-react"
import Modal from "@/components/ui/Modal"
import Notice from "@/components/ui/Notice"

const settingItems = ["프로필 수정", "동의 관리", "데이터 삭제", "회원 탈퇴", "로그아웃"]
const consentItems = [
  "이용약관 (필수)",
  "개인정보 수집·이용 (필수)",
  "건강정보 수집·이용 (필수)",
  "마케팅 (선택)",
]

export default function AccountSettings({
  consents,
  setConsents,
  onEditProfile,
  onLogout,
  onDeleteData,
  onWithdraw,
}: {
  consents: boolean[]
  setConsents: (value: boolean[]) => void
  onEditProfile: () => void
  onLogout: () => void
  onDeleteData: () => void
  onWithdraw: () => void
}) {
  const [action, setAction] = useState<string | null>(null)
  return (
    <>
      <div className="max-w-lg space-y-3">
        {settingItems.map((label) => (
          <button
            key={label}
            onClick={() =>
              label === "프로필 수정" ? onEditProfile() : label === "로그아웃" ? onLogout() : setAction(label)
            }
            className={`flex min-h-16 w-full items-center justify-between rounded-xl border p-4 ${
              label === "회원 탈퇴" || label === "데이터 삭제" ? "text-red-600" : ""
            }`}
          >
            {label}
            <ChevronRight size={18} />
          </button>
        ))}
      </div>
      {action && (
        <Modal title={action} close={() => setAction(null)}>
          {action === "동의 관리" ? (
            <div className="space-y-4">
              {consentItems.map((label, index) => (
                <label key={label} className="flex min-h-12 items-center gap-3">
                  <input
                    type="checkbox"
                    disabled={index < 3}
                    checked={consents[index] ?? false}
                    onChange={(event) =>
                      setConsents(
                        consentItems.map((_, position) =>
                          index === position ? event.target.checked : (consents[position] ?? false),
                        ),
                      )
                    }
                    className="h-5 w-5 accent-blue-600"
                  />
                  {label}
                </label>
              ))}
              <Notice>필수 동의 철회는 회원 탈퇴를 통해 체험할 수 있어요.</Notice>
            </div>
          ) : (
            <>
              <p className="mb-6 leading-7">
                {action === "회원 탈퇴"
                  ? "데모 계정을 종료하고 입력한 정보를 초기화할까요?"
                  : "등록한 복용약과 복약 체크 기록을 삭제할까요? 기본정보와 지병 정보는 남아요."}
              </p>
              <button
                onClick={() => {
                  if (action === "회원 탈퇴") onWithdraw()
                  else onDeleteData()
                  setAction(null)
                }}
                className="min-h-12 w-full rounded-xl bg-red-600 text-white"
              >
                {action === "회원 탈퇴" ? "탈퇴하기" : "데이터 삭제하기"}
              </button>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
