import { Sparkles } from "lucide-react"
import Notice from "@/components/ui/Notice"
import { drugs } from "@/mocks/drugs"
import { slotLabels } from "./InteractionSelection"

// 데모 규칙: 가나다정(0) + 마바사정(4) 조합만 병용금기로 표시한다.
// 백엔드 POST /api/v1/interactions/check (DUR 데이터) 연동 시 응답 기반으로 교체한다.
const isWarningPair = (first: number, second: number) =>
  (first === 0 && second === 4) || (first === 4 && second === 0)

export default function InteractionResult({ selected }: { selected: number[] }) {
  const warning = selected.includes(0) && selected.includes(4)
  const pairCount = (selected.length * (selected.length - 1)) / 2

  return (
    <section className="mb-6 space-y-4">
      <div
        className={`rounded-2xl p-5 font-semibold ${
          warning ? "bg-amber-50 text-amber-800" : "bg-blue-50 text-blue-700"
        }`}
      >
        {warning
          ? `${selected.length}개 약의 ${pairCount}개 조합을 확인했어요 · 주의가 필요한 조합 1개`
          : "등록된 병용금기 정보가 없어요"}
      </div>
      {warning && (
        <div className="space-y-4 rounded-2xl border border-red-200 p-5">
          <span className="rounded-md bg-red-50 px-2.5 py-1 text-sm font-semibold text-red-600">
            병용금기 · 가상 결과
          </span>
          <h3 className="text-lg font-bold">
            {slotLabels[selected.indexOf(0)]} 가나다정 + {slotLabels[selected.indexOf(4)]} 마바사정
          </h3>
          <div className="rounded-xl bg-slate-100 p-4">
            <b className="text-sm">① DUR 등록 내용</b>
            <p className="mt-2 leading-7 text-slate-600">
              가상의 성분 가와 성분 마의 병용 제한 내용입니다. 실제 DUR 데이터가 아닌 화면 구성용 예시입니다.
            </p>
          </div>
          <div className="rounded-xl bg-blue-50 p-4">
            <b className="flex items-center gap-2 text-sm text-blue-700">
              <Sparkles size={17} />② 쉬운 설명
            </b>
            <p className="mt-2 leading-7">
              두 약을 함께 복용하기 전에 약사·의사에게 확인해 주세요. 이 결과는 가상 예시입니다.
            </p>
            <p className="mt-2 text-xs text-slate-500">AI가 위 내용을 쉬운 말로 풀어 설명했어요</p>
          </div>
        </div>
      )}
      <details className="rounded-xl border p-4">
        <summary className="cursor-pointer leading-7">
          나머지 {pairCount - (warning ? 1 : 0)}개 조합 · 등록된 병용금기 정보 없음
        </summary>
        <div className="mt-3 space-y-2 text-sm text-slate-500">
          {selected.flatMap((first, position) =>
            selected
              .slice(position + 1)
              .filter((second) => !isWarningPair(first, second))
              .map((second) => (
                <p key={`${first}-${second}`}>
                  {drugs[first].name} + {drugs[second].name} · 등록 정보 없음
                </p>
              )),
          )}
        </div>
      </details>
      <Notice>
        3개 이상을 동시에 복용할 때의 복합 상호작용은 확인할 수 없고, 약을 2개씩 비교한 결과만 제공해요.
      </Notice>
    </section>
  )
}
