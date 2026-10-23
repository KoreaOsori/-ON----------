import { ApiError, apiFetch } from "@/lib/api/client"

// 사진 인식 공통: 업로드(presign → S3 PUT) → 알약(/pill/*) 또는 처방전(/ocr/prescriptions) 인식
// 백엔드가 pill_model 워커로 전달한다. 문장·버튼은 워커(yakon_pill/yakon_rx)가 만든 것을 그대로 표시한다.

export type PhotoPurpose = "pill" | "prescription"

type PresignResponse = { uploadUrl: string; objectKey: string; expiresIn: number; maxBytes: number }

const ALLOWED = ["image/jpeg", "image/png", "image/webp"]
const MAX_BYTES = 10 * 1024 * 1024
const MAX_SIDE = 2500 // 처방전 OCR 긴 변(2500)과 맞춤

/** 허용 형식(jpg·png·webp)이 아니거나 10MB 를 넘으면 브라우저에서 JPEG 로 바꾼다 (HEIC 등) */
async function normalizeImage(file: File): Promise<Blob> {
  if (ALLOWED.includes(file.type) && file.size <= MAX_BYTES) return file
  const bitmap = await createImageBitmap(file).catch(() => {
    throw new Error("이 사진 형식은 열 수 없어요. jpg·png 사진으로 다시 선택해 주세요.")
  })
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement("canvas")
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("사진 변환에 실패했어요."))), "image/jpeg", 0.92),
  )
}

/** 사진 1장을 업로드 버킷에 올리고 object key 를 돌려준다 */
export async function uploadPhoto(file: File, purpose: PhotoPurpose): Promise<string> {
  const blob = await normalizeImage(file)
  const contentType = ALLOWED.includes(blob.type) ? blob.type : "image/jpeg"
  const presign = await apiFetch<PresignResponse>("/uploads/presign", {
    method: "POST",
    body: { contentType, purpose },
  })
  if (blob.size > presign.maxBytes) throw new Error("사진은 10MB 이하만 올릴 수 있어요.")
  const response = await fetch(presign.uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": contentType },
    body: blob,
  })
  if (!response.ok) throw new Error("사진 업로드에 실패했어요. 잠시 후 다시 시도해 주세요.")
  return presign.objectKey
}

/** 화면에 보여줄 오류 문장 (워커·백엔드가 준 message 우선) */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.detail as { detail?: unknown } | undefined)?.detail
    if (detail && typeof detail === "object" && "message" in detail) return String(detail.message)
    if (typeof detail === "string") return detail
    if (error.status === 401) return "로그인이 필요해요."
    return "사진 인식에 실패했어요. 잠시 후 다시 시도해 주세요."
  }
  return error instanceof Error ? error.message : "사진 인식에 실패했어요."
}

// ───────────────────────────── 알약 (각인 OCR + CNN)
export type PillCandidate = {
  rank: number
  itemSeq: string
  name: string
  company: string
  printFront: string
  printBack: string
  shape: string
  color: string
  etcOtc: string
  score: number
  imageUrl: string | null
}

/** step: top1 · top3 · ask_imprint · imprint_input · ask_color · retake · give_up · quality */
export type PillStep = {
  sessionId: string
  step: string
  message?: string
  buttons?: string[]
  candidates?: PillCandidate[]
  caution?: string
  band?: string
  storageNotice?: string
  savedCrops?: number
}

export type PillHandoff = { itemSeq: string; name: string; company: string; imageUrl: string | null }

export const analyzePill = (body: {
  frontKey: string
  backKey?: string
  saveCrops: boolean
  prevSessionId?: string
}) => apiFetch<PillStep>("/pill/analyze", { method: "POST", body })

export const rejectPill = (sessionId: string, fromStep: string) =>
  apiFetch<PillStep>("/pill/reject", { method: "POST", body: { sessionId, fromStep } })

export const choosePillImprint = (sessionId: string, choice: string) =>
  apiFetch<PillStep>("/pill/imprint-choice", { method: "POST", body: { sessionId, choice } })

export const refinePill = (
  sessionId: string,
  input: { imprintFront?: string; imprintBack?: string; color?: string },
) => apiFetch<PillStep>("/pill/refine", { method: "POST", body: { sessionId, ...input } })

export const confirmPill = (sessionId: string, itemSeq: string) =>
  apiFetch<PillHandoff>("/pill/confirm", { method: "POST", body: { sessionId, itemSeq } })

// ───────────────────────────── 처방전·약봉투 (OCR → 개인정보 차단 → LLM → 허가목록 매칭)
/** ui: 미리 채움 · 확인 필요 · 확인 필요(범위 밖/근거 없음/위치/형식/권장 용법과 다름) · 빈칸 */
export type RxField = { value: string | null; conf: number | null; ui: string; over?: boolean; reason?: string }

export type RxDrug = {
  nameRead: string | null
  decision: string
  auto: boolean
  itemSeq: string | null
  itemName?: string
  confirmed?: boolean
  candidates: { itemSeq: string; itemName: string; status: string }[]
  fields: { dose: RxField; times: RxField; days: RxField }
}

export type RxResult = {
  provider: string
  notice: string
  storage: string | null
  sessionId: string | null
  docType: string | null
  drugs: RxDrug[]
  // 기존 형식 (확신도 높은 숫자만 채워짐, 나머지 null)
  candidates: { name: string; amount: number | null; timesPerDay: number | null; days: number | null }[]
}

export const recognizePrescription = (objectKey: string) =>
  apiFetch<RxResult>("/ocr/prescriptions", { method: "POST", body: { objectKey } })

export const confirmPrescriptionDrug = (sessionId: string, drugIndex: number, itemSeq: string) =>
  apiFetch<{ drug: RxDrug; drugIndex: number }>("/ocr/prescriptions/confirm", {
    method: "POST",
    body: { sessionId, drugIndex, itemSeq },
  })

/** 약 이름 표시: 확정된 허가 품목명 → 1순위 후보 → 읽은 이름 */
export const rxDrugName = (drug: RxDrug) =>
  drug.itemName || (drug.auto ? drug.candidates[0]?.itemName : "") || drug.nameRead || "이름 확인 필요"

/** 숫자 칸 표시값: 빈칸이면 빈 문자열 (0 이나 "null" 로 표시하지 않기) */
export const rxFieldText = (field?: RxField) => (field && field.ui !== "빈칸" && field.value ? field.value : "")

export const needsCheck = (field?: RxField) => !!field && field.ui !== "미리 채움"
