import Link from "next/link"
import { button } from "@/components/ui/styles"

export default function NotFound() {
  return (
    <main className="mx-auto max-w-md px-8 py-24 text-center">
      <h1 className="text-2xl font-bold">페이지를 찾을 수 없어요</h1>
      <p className="mb-8 mt-4 leading-7 text-slate-500">
        주소가 바뀌었거나 삭제된 페이지예요.
      </p>
      <Link href="/" className={`${button} inline-flex items-center`}>
        첫 화면으로 가기
      </Link>
    </main>
  )
}
