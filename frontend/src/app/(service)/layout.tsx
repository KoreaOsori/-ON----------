import type { ReactNode } from "react"

// 챗봇(홈)을 제외한 일반 페이지 공통 레이아웃
export default function ServiceLayout({ children }: { children: ReactNode }) {
  return <main className="mx-auto max-w-[1280px] px-8 pb-16 pt-12 lg:px-12">{children}</main>
}
