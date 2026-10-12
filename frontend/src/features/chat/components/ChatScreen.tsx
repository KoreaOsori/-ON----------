"use client"

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Plus } from "lucide-react"
import { useSession } from "@/providers/SessionProvider"
import useChat from "../hooks/useChat"
import ChatComposer from "./ChatComposer"
import ChatMessageItem from "./ChatMessageItem"
import ChatStatusNotice from "./ChatStatusNotice"
import ChatWelcome from "./ChatWelcome"
import DrugCandidates from "./DrugCandidates"
import GuestProfileModal from "./GuestProfileModal"
import PhotoSourceModal from "./PhotoSourceModal"

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
  const upload = useRef<HTMLInputElement>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const { messages, status, setStatus, remaining, send, reset } = useChat({
    logged,
    profile,
    blocked: candidates,
  })

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, status, candidates])

  const ask = (question: string, confirmed = false) => {
    if (send(question, confirmed)) setText("")
  }
  const login = () => router.push("/mypage")
  const isEmpty = !messages.length && status === "idle" && !candidates

  return (
    <div className="relative mx-auto max-w-[1120px]">
      <div className={`px-10 ${isEmpty ? "pb-8" : "pb-[225px]"}`}>
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
              />
            ))}
            {candidates && (
              <DrugCandidates
                photoType={photoType}
                rejected={rejected}
                onConfirm={(drugName) => {
                  setCandidates(false)
                  setTimeout(() => ask(`${drugName}에 대해 알려주세요`, true), 0)
                }}
                onReject={(drugName) => setRejected((previous) => [...previous, drugName])}
                onRetry={() => {
                  setCandidates(false)
                  setSheet(true)
                }}
              />
            )}
            <ChatStatusNotice
              status={status}
              onRetry={() => ask("가나다정에 대해 알려주세요")}
              onLogin={login}
            />
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
