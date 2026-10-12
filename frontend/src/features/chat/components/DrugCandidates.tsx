import DrugArt from "@/components/ui/DrugArt"
import { drugs } from "@/mocks/drugs"

// 사진 인식 결과 후보 확인 (데모: 앞의 3개 약을 후보로 노출)
export default function DrugCandidates({
  photoType,
  rejected,
  onConfirm,
  onReject,
  onRetry,
}: {
  photoType: string
  rejected: string[]
  onConfirm: (drugName: string) => void
  onReject: (drugName: string) => void
  onRetry: () => void
}) {
  return (
    <div className="rounded-2xl border p-5">
      <h2 className="text-xl font-bold">이 약이 맞나요?</h2>
      <p className="my-3 text-sm text-slate-500">
        {photoType} 인식 데모예요. 확인한 후 안내를 시작해요.
      </p>
      <div className="space-y-3">
        {drugs.slice(0, 3).map(
          (drug, index) =>
            !rejected.includes(drug.name) && (
              <div key={drug.name} className="flex items-center gap-3 rounded-xl bg-slate-50 p-3">
                <DrugArt index={index} />
                <div className="flex-1">
                  <b>{drug.name}</b>
                  <p className="text-xs text-slate-500">{drug.maker}</p>
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => onConfirm(drug.name)}
                      className="min-h-11 rounded-lg bg-blue-600 px-3 text-sm text-white"
                    >
                      이 약이에요
                    </button>
                    <button
                      onClick={() => onReject(drug.name)}
                      className="min-h-11 px-2 text-sm text-slate-500"
                    >
                      아니에요
                    </button>
                  </div>
                </div>
              </div>
            ),
        )}
      </div>
      <button className="mt-4 min-h-11 text-sm text-blue-600" onClick={onRetry}>
        다시 사진 첨부하기
      </button>
    </div>
  )
}
