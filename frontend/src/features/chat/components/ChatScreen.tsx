"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Plus } from "lucide-react"
import { useSession } from "@/providers/SessionProvider"
import type { LlmCandidate } from "../api"
import useChat, { MAX_CHAT_PRODUCTS } from "../hooks/useChat"
import ChatComposer from "./ChatComposer"
import ChatMessageItem, { candidateLabel } from "./ChatMessageItem"
import ChatStatusNotice from "./ChatStatusNotice"
import ChatWelcome from "./ChatWelcome"
import DrugCandidates from "./DrugCandidates"
import GuestProfileModal from "./GuestProfileModal"
import PhotoSourceModal from "./PhotoSourceModal"

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
  const [candidates, setCandidates] = useState(false)
  const [rejected, setRejected] = useState<string[]>([])
  const [photoType, setPhotoType] = useState("")
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
  const isEmpty = !messages.length && status === "idle" && !candidates

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
                  setCandidates(false)
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
            {candidates && (
              <DrugCandidates
                photoType={photoType}
                rejected={rejected}
                onConfirm={(drugName) => {
                  const next = addProducts([drugName])
                  setCandidates(false)
                  setTimeout(() => ask(`${drugName}에 대해 알려주세요`, true, next), 0)
                }}
                onReject={(drugName) => setRejected((previous) => [...previous, drugName])}
                onRetry={() => {
                  setCandidates(false)
                  setSheet(true)
                }}
              />
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
        className="hidden"
        onChange={(event) => {
          // TODO(OCR 연동): 지금은 데모 후보 화면을 띄운다. OCR 결과(제품명 목록)를 받으면
          // 사용자가 확인한 이름을 addProducts(names) 로 넘기면 된다.
          if (event.target.files?.length) {
            setRejected([])
            setCandidates(true)
            setStatus("idle")
          }
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
          onSelect={(label) => {
            setPhotoType(label)
            setSheet(false)
            upload.current?.click()
          }}
          onClose={() => setSheet(false)}
        />
      )}
    </div>
  )
}
