import type { Metadata } from "next"
import type { ReactNode } from "react"
import Header from "@/components/layout/Header"
import SessionProvider from "@/providers/SessionProvider"
import "./globals.css"

export const metadata: Metadata = {
  title: {
    default: "약온 - 일상에 안심을 더하다",
    template: "%s | 약온",
  },
  description:
    "약 정보 확인, 병용 금기 확인, 내 주변 약국 찾기까지. 모든 연령을 위한 챗봇 기반 약 정보 서비스",
  robots: { index: false, follow: false },
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <SessionProvider>
          <div className="min-h-dvh bg-white">
            <Header />
            {children}
          </div>
        </SessionProvider>
      </body>
    </html>
  )
}
