/**
 * 지병 주의: 사용자가 입력한 지병을 약 허가 문서 "다음 환자에는 투여하지 말 것" 항목 줄과 맞춘다 (브라우저에서만, 서버로 보내지 않음).
 * 식약처 DUR 에는 지병-약 금기가 없어서, 허가 문서 문장으로 찾는 것이다 (판정이 아니라 근거 문장 안내).
 *
 * - "투여하지 말 것": 항목이 "질환 목록 + 환자" 꼴이고 그 목록의 한 항목이 지병 이름 그 자체 (예: "3) 고혈압 환자")
 * - "주의": 그 밖에 지병이 언급된 줄 (예: "6) 심한 고혈압 환자", "중증 간장애 환자", "기관지 천식 병력…") — 원문을 보고 판단
 * 2026-10-23 로컬 gold 전수 검토: 문서 전체가 아니라 이 항목 안에서만 찾아야 한다 (이상반응·임상시험 문장이 대량으로 걸림)
 */

type Condition = {
  /** 사용자 입력에 이 말이 있으면 이 지병으로 본다 */
  triggers: string[]
  /** 항목 줄에서 찾는 표기 */
  mention: RegExp
  /** "투여하지 말 것"으로 볼 목록 항목 (정확히 같을 때만) */
  names: string[]
}

const CONDITIONS: Record<string, Condition> = {
  고혈압: { triggers: ["고혈압"], mention: /(?<!폐|폐동맥\s?)고혈압/, names: ["고혈압", "고혈압증"] },
  당뇨: { triggers: ["당뇨"], mention: /당뇨/, names: ["당뇨병", "당뇨"] },
  천식: { triggers: ["천식"], mention: /천식/, names: ["천식", "기관지 천식", "기관지천식"] },
  녹내장: { triggers: ["녹내장"], mention: /녹내장/, names: ["녹내장"] },
  간질환: {
    triggers: ["간질환", "간장애", "간염", "간경화", "간경변", "지방간", "간기능", "간부전"],
    mention: /간장애|간질환|간기능\s?장애|간부전|간경변/,
    names: ["간장애", "간질환", "간기능장애", "간부전", "간경변"],
  },
  신장질환: {
    triggers: ["신장", "신부전", "콩팥", "신기능", "투석"],
    mention: /신장애|신부전|신장질환|신기능\s?장애/,
    names: ["신장애", "신부전", "신장질환", "신기능장애"],
  },
  심부전: { triggers: ["심부전"], mention: /심부전/, names: ["심부전", "울혈성 심부전", "울혈성심부전"] },
  위궤양: {
    triggers: ["위궤양", "소화성궤양", "십이지장궤양", "궤양"],
    mention: /위궤양|소화성\s?궤양|소화궤양/,
    names: ["소화성궤양", "위궤양", "소화궤양"],
  },
  전립선비대: { triggers: ["전립선", "전립샘"], mention: /전립[선샘]비대/, names: ["전립선비대", "전립선비대증"] },
  갑상선질환: {
    triggers: ["갑상선", "갑상샘"],
    mention: /(?<!부)갑상[선샘]/,
    names: ["갑상선기능항진증", "갑상샘기능항진증", "갑상선기능저하증", "갑상샘기능저하증", "갑상선 질환", "갑상샘 질환"],
  },
  뇌전증: { triggers: ["뇌전증", "간질", "경련"], mention: /뇌전증|간질/, names: ["뇌전증", "간질"] },
  통풍: { triggers: ["통풍"], mention: /통풍/, names: ["통풍"] },
  저혈압: { triggers: ["저혈압"], mention: /저혈압/, names: ["저혈압"] },
  고지혈증: { triggers: ["고지혈증", "이상지질혈증", "콜레스테롤"], mention: /고지혈증|이상지질혈증/, names: ["고지혈증", "이상지질혈증"] },
}

// 지병이 아니거나 너무 일반적인 말 (그대로 찾으면 거의 모든 줄이 걸린다)
const NOT_A_CONDITION = new Set([
  "없음", "모름", "없어요", "모르겠어요", "기타", "환자", "질환", "질병", "병", "증상", "약", "복용", "복용중", "중", "있음",
  "있어요", "앓고", "치료", "치료중", "진단", "만성", "급성", "경증", "중증", "심한", "약간", "조금",
])
const ITEM = /^(?:\d+\)|\(\d+\)|[①-⑳]|-)\s*(.+?)\s*(?:등의|등)?\s*환자\.?$/

/** 사용자 지병 입력 → 찾을 지병 목록. 사전에 없는 말(예: 부정맥)도 그대로 찾는다 ("주의"로만) */
export function parseConditions(text: string | undefined) {
  const found = new Map<string, Condition | null>()
  for (const word of (text ?? "").split(/[,\s/·]+/).map((item) => item.trim())) {
    if (word.length < 2 || NOT_A_CONDITION.has(word)) continue
    const known = Object.entries(CONDITIONS).find(([, condition]) =>
      condition.triggers.some((trigger) => word.includes(trigger)),
    )
    if (known) found.set(known[0], known[1])
    else found.set(word, null)
  }
  return found
}

/** 이 줄이 지병 "투여하지 말 것"(true) / "주의"(false) / 무관(null) */
function classify(line: string, name: string, condition: Condition | null): boolean | null {
  if (!(condition ? condition.mention.test(line) : line.includes(name))) return null
  if (!condition) return false
  const match = line.match(ITEM)
  if (!match) return false
  const items = match[1]
    .replace(/\([^)]*\)/g, "") // 괄호 설명은 빼고 목록만
    .split(/,|·|및|또는|\//)
    .map((item) => item.trim())
  return items.some((item) => condition.names.includes(item))
}

export type ConditionCaution = { medicine: string; line: string; contraindicated: boolean }

/** 지병별로, 고른 약들의 "투여하지 말 것" 항목에서 찾은 줄 */
export function matchConditions(
  conditionsText: string | undefined,
  medicines: { name: string; contraindicatedPatients: string[] }[],
) {
  const result = new Map<string, ConditionCaution[]>()
  for (const [name, condition] of parseConditions(conditionsText)) {
    const found: ConditionCaution[] = []
    for (const medicine of medicines) {
      for (const line of medicine.contraindicatedPatients) {
        const kind = classify(line, name, condition)
        if (kind !== null) found.push({ medicine: medicine.name, line, contraindicated: kind })
      }
    }
    // 투여하지 말 것 먼저
    result.set(name, found.sort((a, b) => Number(b.contraindicated) - Number(a.contraindicated)))
  }
  return result
}
