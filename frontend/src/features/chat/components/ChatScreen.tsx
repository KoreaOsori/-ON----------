"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { LoaderCircle, Plus } from "lucide-react"
import {
  analyzePill,
  errorMessage as photoErrorMessage,
  recognizePrescription,
  uploadPhoto,
  type PhotoPurpose,
  type PillStep,
  type RxResult,
} from "@/features/photo/api"
import { useSession } from "@/providers/SessionProvider"
import type { LlmCandidate } from "../api"
import useChat, { MAX_CHAT_PRODUCTS } from "../hooks/useChat"
import ChatComposer from "./ChatComposer"
import ChatMessageItem, { candidateLabel } from "./ChatMessageItem"
import ChatStatusNotice from "./ChatStatusNotice"
import ChatWelcome from "./ChatWelcome"
import GuestProfileModal from "./GuestProfileModal"
import PhotoSourceModal from "./PhotoSourceModal"
import PillDialog from "./PillDialog"
import RxCandidates from "./RxCandidates"

/** 사진 인식 진행 상태: 업로드 → 인식 → 결과(알약 대화 / 처방전 약 목록) */
type PhotoState =
  | { phase: "working"; text: string }
  | { phase: "pill"; step: PillStep }
  | { phase: "rx"; result: RxResult }
  | { phase: "error"; message: string }

const compact = (value: string) => value.replace(/\s+/g, "").toLowerCase()

/** 같은 이름(공백·대소문자 무시)은 한 번만, 최대 개수까지 */
function mergeProducts(current: string[], added: string[]) {
  const merged = [...current]
  for (const name of added.map((item) => item.trim()).filter(Boolean)) {
    if (!merged.some((item) => compact(item) === compact(name))) merged.push(name)
  }
  return merged.slice(0, MAX_CHAT_PRODUCTS)
}

/** 로고를 누르면 homeRevision이 바뀌어 대화가 초기화된다 */
export default function ChatScreen() {
  const { homeRevision } = useSession()
  return <ChatView key={homeRevision} />
}

function ChatView() {
  const router = useRouter()
  const { logged, guestProfile, memberProfile, setGuestProfile } = useSession()
  const profile = logged ? memberProfile : guestProfile

  const [text, setText] = useState("")
  const [profileOpen, setProfileOpen] = useState(false)
  const [healthConsent, setHealthConsent] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [photo, setPhoto] = useState<PhotoState | null>(null)
  const [purpose, setPurpose] = useState<PhotoPurpose>("pill")
  const [saveCrops, setSaveCrops] = useState(false)
  const [prevSession, setPrevSession] = useState<string | undefined>()
  // 사진 결과를 확인하는 동안에는 일반 질문을 막는다 (오류 화면은 제외)
  const candidates = photo !== null && photo.phase !== "error"
  // 사진(알약·처방전)에서 확인한 제품명. 질문할 때 v3 의 products 로 함께 보낸다
  const [products, setProducts] = useState<string[]>([])
  const upload = useRef<HTMLInputElement>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const { messages, status, setStatus, errorMessage, remaining, send, retry, reset } = useChat({
    logged,
    profile,
    blocked: candidates,
  })

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, status, candidates])

  const ask = (question: string, confirmed = false, list = products) => {
    if (send(question, { confirmed, products: list })) setText("")
  }

  /**
   * 사진 인식(OCR) 결과를 받는 곳. OCR 연동 시 인식·확인된 제품명 목록을 이 함수로 넘기면
   * 이후 질문에 products 로 함께 전달된다. 반환값은 합쳐진 목록이다.
   */
  const addProducts = (names: string[]) => {
    const next = mergeProducts(products, names)
    setProducts(next)
    return next
  }

  /** 되묻기 후보를 고르면, 겹치던 이름 대신 "제품명 (제조사)" 를 넣고 같은 질문을 다시 보낸다 */
  const pickCandidate = (candidate: LlmCandidate, question: string, sent: string[]) => {
    const chosen = compact(candidate.product_name)
    const kept = sent.filter((name) => !chosen.startsWith(compact(name)))
    const next = mergeProducts(kept, [candidateLabel(candidate)])
    setProducts(next)
    ask(question, true, next)
  }

  const login = () => router.push("/mypage")

  // 사진 선택 → 업로드(presign) → 사진 종류에 따라 알약(OCR+CNN) / 처방전(OCR+LLM) 인식
  const recognize = async (files: File[]) => {
    setStatus("idle")
    try {
      setPhoto({ phase: "working", text: "사진을 올리고 있어요" })
      if (purpose === "pill") {
        const [frontKey, backKey] = await Promise.all(files.slice(0, 2).map((file) => uploadPhoto(file, "pill")))
        setPhoto({ phase: "working", text: "알약을 확인하고 있어요 (최대 1분)" })
        const step = await analyzePill({ frontKey, backKey, saveCrops, prevSessionId: prevSession })
        setPhoto({ phase: "pill", step })
      } else {
        const key = await uploadPhoto(files[0], "prescription")
        setPhoto({ phase: "working", text: "처방전을 읽고 있어요 (최대 1분)" })
        setPhoto({ phase: "rx", result: await recognizePrescription(key) })
      }
    } catch (error) {
      setPhoto({ phase: "error", message: photoErrorMessage(error) })
    } finally {
      setPrevSession(undefined)
    }
  }
  // 사진에서 사용자가 확인한 약 → products 에 더하고 그 약으로 질문 시작
  const askAbout = (drugName: string) => {
    const next = addProducts([drugName])
    setPhoto(null)
    setTimeout(() => ask(`${drugName}에 대해 알려주세요`, true, next), 0)
  }
  const reopen = (prev?: string) => {
    setPhoto(null)
    setPrevSession(prev)
    if (prev) {
      // 재촬영은 같은 알약 종류로 바로 사진 선택
      setPurpose("pill")
      if (upload.current) upload.current.multiple = true
      upload.current?.click()
    } else setSheet(true)
  }
  const isEmpty = !messages.length && status === "idle" && photo === null

  return (
    <div className="relative mx-auto max-w-[1120px]">
      <div className={`px-10 ${isEmpty ? "pb-8" : products.length ? "pb-[270px]" : "pb-[225px]"}`}>
        {isEmpty ? (
          <ChatWelcome />
        ) : (
          <section className="mx-auto max-w-3xl space-y-6 pt-8">
            <div className="flex items-center justify-between text-sm text-slate-500">
              <span>약온과의 대화</span>
              <button
                className="min-h-11 px-3"
                onClick={() => {
                  reset()
                  setPhoto(null)
                  setProducts([])
                }}
              >
                새 대화 <Plus size={15} className="ml-1 inline" />
              </button>
            </div>
            {messages.map((message, index) => (
              <ChatMessageItem
                key={index}
                message={message}
                showFollowUps={index === messages.length - 1}
                followUpDisabled={status === "loading" || candidates}
                onFollowUp={(question) => ask(question)}
                onPickCandidate={(candidate) => pickCandidate(candidate, message.question, message.products)}
              />
            ))}
            {photo?.phase === "working" && (
              <div className="flex items-center gap-3 rounded-2xl border p-5 text-slate-600">
                <LoaderCircle className="animate-spin text-blue-600" size={24} />
                {photo.text}
              </div>
            )}
            {photo?.phase === "error" && (
              <div className="rounded-2xl border p-5">
                <p className="text-sm text-red-600">{photo.message}</p>
                <button className="mt-3 min-h-11 text-sm text-blue-600" onClick={() => reopen()}>
                  다시 사진 첨부하기
                </button>
              </div>
            )}
            {photo?.phase === "pill" && (
              <PillDialog initial={photo.step} onConfirm={askAbout} onRetake={(sid) => reopen(sid)} />
            )}
            {photo?.phase === "rx" && (
              <RxCandidates result={photo.result} onAsk={askAbout} onRetry={() => reopen()} />
            )}
            <ChatStatusNotice status={status} errorMessage={errorMessage} onRetry={retry} onLogin={login} />
            <div ref={bottom} />
          </section>
        )}
      </div>
      <ChatComposer
        docked={!isEmpty}
        logged={logged}
        profile={profile}
        remaining={remaining}
        text={text}
        setText={setText}
        disabled={candidates}
        sendDisabled={!text.trim() || status === "loading" || candidates}
        products={products}
        onRemoveProduct={(name) => setProducts((previous) => previous.filter((item) => item !== name))}
        onSubmit={() => ask(text)}
        onOpenProfile={() => setProfileOpen(true)}
        onOpenPhoto={() => setSheet(true)}
      />
      <input
        ref={upload}
        type="file"
        accept="image/*"
        multiple={purpose === "pill"}
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? [])
          if (files.length) recognize(files)
          event.target.value = ""
        }}
      />
      {profileOpen && (
        <GuestProfileModal
          profile={profile}
          consent={healthConsent}
          setConsent={setHealthConsent}
          onApply={(value) => {
            setGuestProfile(value)
            setProfileOpen(false)
          }}
          onClose={() => setProfileOpen(false)}
        />
      )}
      {sheet && (
        <PhotoSourceModal
          saveCrops={saveCrops}
          setSaveCrops={setSaveCrops}
          onSelect={(value) => {
            setPurpose(value)
            setSheet(false)
            // 다시 그리기 전에 바로 열리므로 여러 장 선택 여부를 직접 지정
            if (upload.current) upload.current.multiple = value === "pill"
            upload.current?.click()
          }}
          onClose={() => setSheet(false)}
        />
      )}
    </div>
  )
}
