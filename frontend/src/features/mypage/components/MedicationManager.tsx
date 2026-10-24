"use client"

import { useState } from "react"
import { Camera, Pencil, Pill, Plus, Trash2 } from "lucide-react"
import Modal from "@/components/ui/Modal"
import { button, inputClass } from "@/components/ui/styles"
import type { HealthProfile, RegisteredMedication } from "@/types/health"
import { dosageText, emptyMedication, isFinished, myMedicines } from "../medications"

const fields: { key: keyof RegisteredMedication; label: string; type: string; unit?: string }[] = [
  { key: "amount", label: "1회 복용량", type: "number", unit: "정" },
  { key: "times", label: "하루 횟수", type: "number", unit: "회" },
  { key: "days", label: "복용 일수", type: "number", unit: "일" },
  { key: "start", label: "시작일", type: "date" },
]

function MedicationForm({
  value,
  editName,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  value: RegisteredMedication
  /** 새로 추가할 때만 이름을 입력받는다 (이미 있는 약은 삭제 후 다시 추가) */
  editName: boolean
  onSubmit: (value: RegisteredMedication) => void
  onCancel: () => void
  submitLabel: string
}) {
  const [draft, setDraft] = useState(value)
  const invalid =
    !draft.name.trim() ||
    fields.some(({ key, type }) => type === "number" && draft[key] !== "" && !(Number(draft[key]) >= 1))
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        if (!invalid) onSubmit(draft)
      }}
      className="space-y-3 rounded-xl bg-slate-50 p-4"
    >
      {editName && (
        <label className="block text-sm">
          약 이름
          <input
            autoFocus
            required
            maxLength={100}
            className={`${inputClass} mt-1`}
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            placeholder="예: 타이레놀정500밀리그람"
          />
        </label>
      )}
      <div className="grid grid-cols-2 gap-3">
        {fields.map(({ key, label, type, unit }) => (
          <label key={key} className="block text-sm">
            {label}
            {unit && <span className="text-slate-400"> ({unit})</span>}
            <input
              type={type}
              min={type === "number" ? 1 : undefined}
              className={`${inputClass} mt-1`}
              value={draft[key]}
              onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
            />
          </label>
        ))}
      </div>
      <p className="text-xs text-slate-500">모르는 칸은 비워 두어도 돼요. 하루 횟수를 넣으면 체크리스트가 시간대별로 나뉘어요.</p>
      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="min-h-11 flex-1 rounded-xl border bg-white">
          취소
        </button>
        <button disabled={invalid} className={`${button} min-h-11 flex-1 py-2`}>
          {submitLabel}
        </button>
      </div>
    </form>
  )
}

export default function MedicationManager({
  profile,
  onSave,
  onRemove,
  onClose,
  onRegisterByPhoto,
}: {
  profile: HealthProfile
  /** 서버에 저장. 성공하면 true */
  onSave: (item: RegisteredMedication) => Promise<boolean>
  onRemove: (name: string) => Promise<boolean>
  onClose: () => void
  onRegisterByPhoto: () => void
}) {
  // editing: 수정 중인 약 이름, "" 는 새 약 추가
  const [editing, setEditing] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const medicines = myMedicines(profile)
  const save = async (item: RegisteredMedication) => {
    if (await onSave(item)) setEditing(null)
  }

  return (
    <Modal title="내 복용약" close={onClose}>
      {!medicines.length && editing === null && (
        <p className="py-6 text-center leading-7 text-slate-500">아직 등록한 약이 없어요.</p>
      )}
      <ul className="space-y-3">
        {medicines.map((drug) => (
          <li key={drug.name} className="rounded-2xl border p-4">
            <div className="flex items-start gap-3">
              <Pill className="mt-0.5 shrink-0 text-blue-600" size={20} />
              <div className="min-w-0 flex-1">
                <b className="break-words font-medium">{drug.name}</b>
                <p className="mt-1 text-sm text-slate-600">
                  {drug.info && dosageText(drug.info) ? dosageText(drug.info) : "복용 정보 없음"}
                </p>
                <p className="text-xs text-slate-400">
                  {drug.source}
                  {isFinished(drug.info) && <span className="ml-2 text-amber-700">복용 기간이 끝났어요</span>}
                </p>
              </div>
              {editing !== drug.name && confirmDelete !== drug.name && (
                <div className="flex shrink-0">
                  <button
                    aria-label={`${drug.name} 수정`}
                    onClick={() => {
                      setEditing(drug.name)
                      setConfirmDelete(null)
                    }}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-50"
                  >
                    <Pencil size={17} />
                  </button>
                  <button
                    aria-label={`${drug.name} 삭제`}
                    onClick={() => {
                      setConfirmDelete(drug.name)
                      setEditing(null)
                    }}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-red-500 hover:bg-red-50"
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              )}
            </div>
            {confirmDelete === drug.name && (
              <div className="mt-3 flex items-center gap-2 rounded-xl bg-red-50 p-3 text-sm">
                <span className="flex-1 text-red-700">다 먹었거나 더 이상 먹지 않나요? 목록에서 삭제할게요.</span>
                <button onClick={() => setConfirmDelete(null)} className="min-h-11 rounded-lg bg-white px-3">
                  취소
                </button>
                <button
                  onClick={async () => {
                    if (await onRemove(drug.name)) setConfirmDelete(null)
                  }}
                  className="min-h-11 rounded-lg bg-red-600 px-3 text-white"
                >
                  삭제
                </button>
              </div>
            )}
            {editing === drug.name && (
              <div className="mt-3">
                <MedicationForm
                  value={drug.info ?? emptyMedication(drug.name)}
                  editName={false}
                  submitLabel="저장"
                  onSubmit={save}
                  onCancel={() => setEditing(null)}
                />
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-5">
        {editing === "" ? (
          <MedicationForm
            value={emptyMedication()}
            editName
            submitLabel="추가"
            // 이미 있는 이름이면 새로 만들지 않고 그 약의 복용 정보를 바꾼다
            onSubmit={save}
            onCancel={() => setEditing(null)}
          />
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => {
                setEditing("")
                setConfirmDelete(null)
              }}
              className="flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl border border-blue-200 bg-blue-50 font-medium text-blue-700"
            >
              <Plus size={18} />
              직접 추가
            </button>
            <button
              onClick={onRegisterByPhoto}
              className="flex min-h-12 flex-1 items-center justify-center gap-2 rounded-xl border font-medium"
            >
              <Camera size={18} />
              처방전으로 등록
            </button>
          </div>
        )}
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">
        복용약은 내 계정에 저장돼요. 약을 바꾸거나 끊기 전에는 의사·약사와 상담하세요.
      </p>
    </Modal>
  )
}
