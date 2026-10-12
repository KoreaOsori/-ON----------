"use client"

import Image from "next/image"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { MapPin, MessageCircle, Pill, UserRound } from "lucide-react"
import brandLogo from "@/assets/brand-logo.png"
import { useSession } from "@/providers/SessionProvider"

const menus = [
  { path: "/", label: "챗봇", icon: MessageCircle },
  { path: "/medicine", label: "약정보", icon: Pill },
  { path: "/pharmacy", label: "내 주변 약국", icon: MapPin },
  { path: "/mypage", label: "마이페이지", icon: UserRound },
]

export default function Header() {
  const pathname = usePathname()
  const router = useRouter()
  const { logged, resetHome } = useSession()

  return (
    <header className="relative z-20 border-b border-slate-100 bg-white">
      <div className="mx-auto flex min-h-24 max-w-[1360px] flex-wrap items-center justify-between gap-x-8 px-8 lg:px-12">
        <Link
          href="/"
          className="flex min-h-16 flex-col items-start justify-center py-3"
          aria-label="약온 첫 화면으로 돌아가기"
          onClick={() => {
            resetHome()
            window.scrollTo({ top: 0, behavior: "smooth" })
          }}
        >
          <span className="relative block h-[52px] w-[176px] overflow-hidden">
            <Image
              src={brandLogo}
              alt="약온"
              priority
              className="absolute -left-[74px] -top-[44px] w-[320px] max-w-none"
            />
          </span>
          <span className="mt-1 pl-1 text-xs font-medium tracking-normal text-slate-500">
            일상에 안심을 더하다
          </span>
        </Link>
        <nav aria-label="주 메뉴" className="flex flex-wrap items-center gap-5 lg:gap-10">
          {menus.map((menu) => {
            const isActive =
              menu.path === "/" ? pathname === "/" : pathname.startsWith(menu.path)
            return (
              <Link
                key={menu.path}
                href={menu.path}
                aria-current={isActive ? "page" : undefined}
                className={`flex h-24 items-center gap-2 whitespace-nowrap border-b-2 px-1 text-base font-semibold ${
                  isActive
                    ? "border-blue-600 text-blue-600"
                    : "border-transparent text-slate-500 hover:text-slate-900"
                }`}
              >
                <menu.icon size={19} strokeWidth={1.8} />
                {menu.label}
              </Link>
            )
          })}
        </nav>
        <button
          onClick={() => router.push("/mypage")}
          className="flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 px-4 text-sm font-medium"
        >
          <UserRound size={17} />
          {logged ? "내 계정" : "로그인"}
        </button>
      </div>
    </header>
  )
}
