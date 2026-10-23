/** 사용자 건강정보(임신 여부·나이)에 해당하는 DUR 주의 표시. 색은 병용 확인의 "성분 기준 주의" 표시와 같다 */
export default function MineBadge() {
  return (
    <span className="ml-2 rounded-md bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700">
      내 정보에 해당
    </span>
  )
}
